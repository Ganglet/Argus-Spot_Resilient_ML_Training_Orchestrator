"""Track 2 benchmark training job — shared by all four arms.

Same CNN architecture as ml/cifar10_job/train.py. What differs between arms is
purely the checkpoint policy (see arms/*.json), so all four arms run this one
script; the harness picks the policy via --arm-config.

Checkpoint policies:
  none       — never checkpoints. A kill always restarts at step 0.
  periodic   — checkpoints every N steps regardless of any signal.
  reactive   — checkpoints only when the harness drops a NOTICE trigger file
               in the run dir (stands in for SIGTERM / AWS's 2-min notice).
  predictive — checkpoints only when the harness drops a RISK trigger file
               (stands in for the operator's early risk-score signal).

Triggers are plain files polled once per step rather than OS signals: this
run dir/NOTICE and run dir/RISK mirror the production system's own
S3 `_FLUSH_TRIGGER` marker-polling design (see docs/B5_cifar10_checkpointing.md),
and — unlike POSIX signal delivery — behave identically on every dev machine
and CI runner the harness might execute on.
"""
import argparse
import json
import os
import time

import torch
import torch.nn as nn
import torch.optim as optim

from metrics_logger import log_event

try:
    import torchvision
    import torchvision.transforms as transforms
    HAS_TORCHVISION = True
except ImportError:
    HAS_TORCHVISION = False


class SimpleCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(3, 16, 3, padding=1)
        self.pool = nn.MaxPool2d(2, 2)
        self.fc1 = nn.Linear(16 * 16 * 16, 120)
        self.fc2 = nn.Linear(120, 10)

    def forward(self, x):
        x = self.pool(torch.relu(self.conv1(x)))
        x = x.view(-1, 16 * 16 * 16)
        x = torch.relu(self.fc1(x))
        return self.fc2(x)


def build_dataloader(batch_size, data_root, synthetic):
    if not synthetic and HAS_TORCHVISION:
        transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
        ])
        dataset = torchvision.datasets.CIFAR10(root=data_root, train=True, download=True, transform=transform)
        return torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True, num_workers=0)

    # Synthetic fallback: CIFAR-10-shaped random tensors. The benchmark measures
    # interruption/recovery behavior, not accuracy, so no real dataset is required
    # (see "Fast config" in docs/phase6_remaining.md Track 2).
    images = torch.randn(512, 3, 32, 32)
    labels = torch.randint(0, 10, (512,))
    dataset = torch.utils.data.TensorDataset(images, labels)
    return torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True, num_workers=0)


def checkpoint_path(run_dir):
    return os.path.join(run_dir, "checkpoint.pt")


def save_checkpoint(run_dir, model, optimizer, step):
    path = checkpoint_path(run_dir)
    torch.save({"step": step, "model_state_dict": model.state_dict(), "optimizer_state_dict": optimizer.state_dict()}, path)
    return os.path.getsize(path)


def load_checkpoint(run_dir, model, optimizer):
    path = checkpoint_path(run_dir)
    if not os.path.exists(path):
        return None
    ckpt = torch.load(path, weights_only=True)
    model.load_state_dict(ckpt["model_state_dict"])
    optimizer.load_state_dict(ckpt["optimizer_state_dict"])
    return ckpt["step"]


def check_trigger(run_dir, filename):
    trigger_path = os.path.join(run_dir, filename)
    if os.path.exists(trigger_path):
        os.remove(trigger_path)
        return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--arm-config", required=True)
    parser.add_argument("--step-budget", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--step-time-sec", type=float, default=0.05, help="minimum wall-clock time per step")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--data-root", default=os.path.join(os.path.dirname(__file__), "data"))
    args = parser.parse_args()

    with open(args.arm_config) as f:
        arm = json.load(f)

    checkpoint_mode = arm["checkpoint_mode"]
    step_budget = args.step_budget or arm.get("step_budget", 200)
    events_path = os.path.join(args.run_dir, "events.jsonl")

    model = SimpleCNN()
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.001, momentum=0.9)

    resumed_step = load_checkpoint(args.run_dir, model, optimizer) if checkpoint_mode != "none" else None
    start_step = resumed_step + 1 if resumed_step is not None else 0
    log_event(events_path, "resumed" if resumed_step is not None else "started",
               arm=arm["name"], start_step=start_step, step_budget=step_budget)

    loader = build_dataloader(args.batch_size, args.data_root, args.synthetic or not HAS_TORCHVISION)
    data_iter = iter(loader)

    interval = arm.get("checkpoint_interval_steps")

    for step in range(start_step, step_budget):
        try:
            inputs, labels = next(data_iter)
        except StopIteration:
            data_iter = iter(loader)
            inputs, labels = next(data_iter)

        t0 = time.time()
        optimizer.zero_grad()
        outputs = model(inputs)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()
        elapsed = time.time() - t0
        if elapsed < args.step_time_sec:
            time.sleep(args.step_time_sec - elapsed)

        log_event(events_path, "step", step=step, loss=loss.item())

        if checkpoint_mode == "periodic" and interval and step > 0 and step % interval == 0:
            size = save_checkpoint(args.run_dir, model, optimizer, step)
            log_event(events_path, "checkpoint", policy="periodic", step=step, bytes=size)
        elif checkpoint_mode == "reactive" and check_trigger(args.run_dir, "NOTICE"):
            size = save_checkpoint(args.run_dir, model, optimizer, step)
            log_event(events_path, "checkpoint", policy="reactive", step=step, bytes=size)
        elif checkpoint_mode == "predictive" and check_trigger(args.run_dir, "RISK"):
            size = save_checkpoint(args.run_dir, model, optimizer, step)
            log_event(events_path, "checkpoint", policy="predictive", step=step, bytes=size)

    log_event(events_path, "finished", step=step_budget - 1)


if __name__ == "__main__":
    main()
