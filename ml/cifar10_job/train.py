import os
import sys
import signal

import boto3
import torch
import torch.nn as nn
import torch.optim as optim
import torchvision
import torchvision.transforms as transforms

# S3_BUCKET and S3_PREFIX must align with the CRD's checkpointPath.
# checkpointPath: s3://argus-checkpoints-844641713781/checkpoints/cifar10-test
# → S3_BUCKET = argus-checkpoints-844641713781
# → S3_PREFIX = checkpoints/cifar10-test/latest_checkpoint.pt
# → trigger key = checkpoints/cifar10-test/_FLUSH_TRIGGER  (written by operator)
S3_BUCKET = os.environ.get("S3_BUCKET", "argus-checkpoints-844641713781")
S3_PREFIX = os.environ.get("S3_PREFIX", "checkpoints/cifar10-test/latest_checkpoint.pt")
LOCAL_CHECKPOINT_PATH = "checkpoint.pt"

s3_client = boto3.client(
    "s3",
    endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),  # LocalStack in dev, unset on EKS
    region_name=os.environ.get("AWS_DEFAULT_REGION", "eu-north-1"),
)


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


def save_checkpoint(model, optimizer, epoch):
    print(f"Saving checkpoint (epoch {epoch}) → s3://{S3_BUCKET}/{S3_PREFIX}")
    torch.save(
        {"epoch": epoch, "model_state_dict": model.state_dict(), "optimizer_state_dict": optimizer.state_dict()},
        LOCAL_CHECKPOINT_PATH,
    )
    try:
        s3_client.upload_file(LOCAL_CHECKPOINT_PATH, S3_BUCKET, S3_PREFIX)
        print("Checkpoint uploaded.")
    except Exception as e:
        print(f"Checkpoint upload failed: {e}")


def load_checkpoint(model, optimizer):
    print(f"Loading checkpoint from s3://{S3_BUCKET}/{S3_PREFIX}")
    try:
        s3_client.download_file(S3_BUCKET, S3_PREFIX, LOCAL_CHECKPOINT_PATH)
        ckpt = torch.load(LOCAL_CHECKPOINT_PATH)
        model.load_state_dict(ckpt["model_state_dict"])
        optimizer.load_state_dict(ckpt["optimizer_state_dict"])
        start = ckpt["epoch"] + 1
        print(f"Resuming from epoch {start}")
        return start
    except Exception as e:
        print(f"No checkpoint found — starting fresh. ({e})")
        return 0


model = SimpleCNN()
criterion = nn.CrossEntropyLoss()
optimizer = optim.SGD(model.parameters(), lr=0.001, momentum=0.9)
current_epoch = 0


def handle_sigterm(*args):
    print("SIGTERM received — flushing checkpoint before exit")
    save_checkpoint(model, optimizer, current_epoch)
    sys.exit(0)


signal.signal(signal.SIGTERM, handle_sigterm)


def check_flush_trigger(epoch):
    """
    Checks if the operator dropped a _FLUSH_TRIGGER marker in S3.
    Trigger key mirrors the operator's trigger_s3_checkpoint() path:
        {prefix_dir}/_FLUSH_TRIGGER
    """
    prefix_dir = S3_PREFIX.rsplit("/", 1)[0]
    trigger_key = f"{prefix_dir}/_FLUSH_TRIGGER"
    try:
        s3_client.head_object(Bucket=S3_BUCKET, Key=trigger_key)
        print("Operator flush trigger detected — saving checkpoint early")
        save_checkpoint(model, optimizer, epoch)
        s3_client.delete_object(Bucket=S3_BUCKET, Key=trigger_key)
    except Exception:
        pass


def main():
    global current_epoch

    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
    ])
    trainset = torchvision.datasets.CIFAR10(root="./data", train=True, download=True, transform=transform)
    trainloader = torch.utils.data.DataLoader(trainset, batch_size=32, shuffle=True, num_workers=2)

    start_epoch = load_checkpoint(model, optimizer)
    epochs = int(os.environ.get("EPOCHS", "5"))

    for epoch in range(start_epoch, epochs):
        current_epoch = epoch
        running_loss = 0.0

        for i, (inputs, labels) in enumerate(trainloader):
            optimizer.zero_grad()
            outputs = model(inputs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            running_loss += loss.item()
            if i % 200 == 199:
                print(f"[epoch {epoch+1}, batch {i+1}] loss: {running_loss / 200:.3f}")
                running_loss = 0.0

            if i % 100 == 0:
                check_flush_trigger(epoch)

        save_checkpoint(model, optimizer, epoch)

    print("Training complete.")


if __name__ == "__main__":
    main()
