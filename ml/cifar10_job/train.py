import os
import sys
import boto3
import torch
import torch.nn as nn
import torch.optim as optim
import torchvision
import torchvision.transforms as transforms
import signal

# Environment variables for S3 Checkpointing
S3_BUCKET = os.environ.get("S3_BUCKET", "argus-model-checkpoints")
S3_PREFIX = os.environ.get("S3_PREFIX", "cifar10-job/latest_checkpoint.pt")
LOCAL_CHECKPOINT_PATH = "checkpoint.pt"

s3_client = boto3.client('s3')

class SimpleCNN(nn.Module):
    def __init__(self):
        super(SimpleCNN, self).__init__()
        self.conv1 = nn.Conv2d(3, 16, 3, padding=1)
        self.pool = nn.MaxPool2d(2, 2)
        self.fc1 = nn.Linear(16 * 16 * 16, 120)
        self.fc2 = nn.Linear(120, 10)

    def forward(self, x):
        x = self.pool(torch.relu(self.conv1(x)))
        x = x.view(-1, 16 * 16 * 16)
        x = torch.relu(self.fc1(x))
        x = self.fc2(x)
        return x

def save_checkpoint_to_s3(model, optimizer, epoch):
    print(f"Saving checkpoint to S3: s3://{S3_BUCKET}/{S3_PREFIX}")
    checkpoint = {
        'epoch': epoch,
        'model_state_dict': model.state_dict(),
        'optimizer_state_dict': optimizer.state_dict()
    }
    torch.save(checkpoint, LOCAL_CHECKPOINT_PATH)
    try:
        s3_client.upload_file(LOCAL_CHECKPOINT_PATH, S3_BUCKET, S3_PREFIX)
        print("Checkpoint uploaded successfully.")
    except Exception as e:
        print(f"Failed to upload checkpoint: {e}")

def load_checkpoint_from_s3(model, optimizer):
    print(f"Attempting to load checkpoint from S3: s3://{S3_BUCKET}/{S3_PREFIX}")
    try:
        s3_client.download_file(S3_BUCKET, S3_PREFIX, LOCAL_CHECKPOINT_PATH)
        checkpoint = torch.load(LOCAL_CHECKPOINT_PATH)
        model.load_state_dict(checkpoint['model_state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        start_epoch = checkpoint['epoch'] + 1
        print(f"Resuming from epoch {start_epoch}")
        return start_epoch
    except Exception as e:
        print(f"No checkpoint found or failed to load. Starting from scratch. ({e})")
        return 0

model = SimpleCNN()
criterion = nn.CrossEntropyLoss()
optimizer = optim.SGD(model.parameters(), lr=0.001, momentum=0.9)

def handle_sigterm(*args):
    print("Caught SIGTERM! Spot interruption imminent. Flushing checkpoint to S3...")
    # Passing a dummy epoch (or we could track it globally)
    save_checkpoint_to_s3(model, optimizer, epoch=999) 
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)

def main():
    transform = transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))])
    
    # Download dataset
    trainset = torchvision.datasets.CIFAR10(root='./data', train=True, download=True, transform=transform)
    trainloader = torch.utils.data.DataLoader(trainset, batch_size=32, shuffle=True, num_workers=2)

    # Resume from checkpoint if it exists
    start_epoch = load_checkpoint_from_s3(model, optimizer)

    epochs = int(os.environ.get("EPOCHS", 5))

    for epoch in range(start_epoch, epochs):
        running_loss = 0.0
        for i, data in enumerate(trainloader, 0):
            inputs, labels = data
            optimizer.zero_grad()
            outputs = model(inputs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            running_loss += loss.item()
            if i % 200 == 199:
                print(f'[{epoch + 1}, {i + 1:5d}] loss: {running_loss / 200:.3f}')
                running_loss = 0.0

            # Check if operator triggered S3 flush
            if i % 100 == 0:
                try:
                    trigger_key = f"{S3_PREFIX.rsplit('/', 1)[0]}/_FLUSH_TRIGGER"
                    s3_client.head_object(Bucket=S3_BUCKET, Key=trigger_key)
                    print("S3 checkpoint trigger detected! Flushing to S3...")
                    save_checkpoint_to_s3(model, optimizer, epoch)
                    s3_client.delete_object(Bucket=S3_BUCKET, Key=trigger_key)
                except Exception:
                    pass  # No trigger file found

        # Save checkpoint at the end of each epoch
        save_checkpoint_to_s3(model, optimizer, epoch)

    print('Finished Training')

if __name__ == "__main__":
    main()
