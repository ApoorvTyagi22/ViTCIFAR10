# -*- coding: utf-8 -*-
"""TrafficSignClassificationVT.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1uKebRbHP08aiZd1MRmYHi5iRnGK9M1Fz
"""
#-----------------------------------------------------------------------------------
import torch # type: ignore
from torchvision.datasets import CIFAR10 # type: ignore
import matplotlib.pyplot as plt # type: ignore
from random import random
from torchvision.transforms import Resize, ToTensor # type: ignore
from torchvision.transforms.functional import to_pil_image # type: ignore
from torchvision.transforms import ToPILImage # type: ignore
from einops.layers.torch import Rearrange # type: ignore
from torch import Tensor # type: ignore
import math
from dataclasses import dataclass
import torch.nn as nn # type: ignore
from torch.nn import functional as F # type: ignore
from einops import rearrange # type: ignore
from einops import repeat # type: ignore 
from torch.utils.data import random_split # type: ignore
from torch.utils.data import DataLoader # type: ignore
from torchvision.transforms import ToPILImage # type: ignore
from torch.utils.data import random_split # type: ignore
from torch.optim.lr_scheduler import CosineAnnealingLR # type: ignore
from sklearn.metrics import confusion_matrix # type: ignore
import seaborn as sns
from google.colab import files # type: ignore
import numpy as np
import matplotlib.pyplot as plt
import os

#-----------------------------------------------------------------------------------


to_tensor = [Resize((144, 144)), ToTensor()]

class Compose(object):
    def __init__(self, transforms):
        """Class to compose multiple transforms together.

        Args:
            transforms (list): List of transforms to compose.
        """
        self.transforms = transforms

    def __call__(self, image):
        for t in self.transforms: # making sure both the transformations happen sequentially in the pipeline
            image = t(image)
        return image

dataset = CIFAR10(root=".", download=True, transform=Compose(to_tensor)) #download in the same directory
print(type(dataset))

        
        
def show_images(dataset, num_samples=10, cols=2):
    """Display a grid of sample images from the dataset.

    Args:
        dataset (torchvision.datasets): The dataset object.
        num_samples (int, optional): Number of samples to display. Defaults to 10.
        cols (int, optional): Number of columns in the grid. Defaults to 2.
    """
    plt.figure(figsize=(15, 15))  # Set up the canvas for the grid

    # Calculate the number of rows needed
    rows = (num_samples + cols - 1) // cols

    # Initialize ToPILImage transform to convert tensors to PIL images for plotting
    to_pil_image = ToPILImage()

    # Ensure num_samples does not exceed the length of the dataset
    num_samples = min(num_samples, len(dataset))

    # Select indices evenly spaced across the dataset
    indices = [i * max(1, len(dataset) // num_samples) for i in range(num_samples)]

    for i, idx in enumerate(indices):
        img, target = dataset[idx]
        plt.subplot(rows, cols, i + 1)
        plt.imshow(to_pil_image(img))
        plt.title(f'Label: {target}', fontsize=12, pad=5, color='black', backgroundcolor='white')
        plt.axis('off')  # Turn off axes for cleaner visualization

    plt.show()

# Call the function to display images
show_images(dataset, num_samples=10, cols=2)
#---------------------------------------------------------------------------------------------------

class Config:
    """Configuration class to store hyperparameters and settings."""
    # hyperparameters for the model
    patch_size = 16
    emb_size = 256
    n_head = 8
    ch = 3
    img_size = 144
    n_layers = 12
    out_dim = 10    
 #---------------------------------------------------------------------------------------------------

class PatchEmbedding(nn.Module):
    def __init__(self, in_channels=Config.ch, patch_size=Config.patch_size, emb_size=Config.emb_size):
        """initialize PatchEmbedding module. 
        Args:
            in_channels (int, optional): Number of input channels.
            patch_size (int, optional): Size of the patch.
            emb_size (int, optional): Size of the embedding.
        """
        super().__init__()        
        self.patch_size = patch_size
        self.projection = nn.Sequential(
            # break-down the image in s1 x s2 patches and flat them
            # rearranges it from batch channel length width to batch, number of patches, flatened size of each patch
            nn.Linear(patch_size * patch_size * in_channels, emb_size)
            )
    def forward(self, x):
        """Method for forward pass.
        Args:
            x (tensor): Input tensor.
        Returns:
            tesnor: a tensor of shape (B, N, E) where N is the number of patches, E is the embedding size.
        """
        x = rearrange(x, 'b c (h p1) (w p2) -> b (h w) (p1 p2 c)', p1=self.patch_size, p2=self.patch_size)
        x = self.projection(x)
        return x
#---------------------------------------------------------------------------------------------------

class SelfAttention(nn.Module):

    def __init__(self, n_embd=Config.emb_size, n_head=Config.n_head):
        """initialize SelfAttention module.

        Args:
            n_embd (int, optional): Embedding dimension. 
            n_head (int, optional): Number of heads.
        """
        super().__init__()
        assert n_embd % n_head == 0
        self.c_attn = nn.Linear(n_embd, 3 * n_embd)
        self.c_proj = nn.Linear(n_embd, n_embd)
        self.c_proj.NANOGPT_SCALE_INIT = 1
        self.n_head = n_head
        self.n_embd = n_embd

    def forward(self, x):
        """Method for forward pass.
        Args:
            x (tensor): input tensor.
        Returns:
            tensor: output of self-attention module.
        """
        B, T, C = x.size() #Batch, sequence length, embedding dimension (1,5,128)
        qkv = self.c_attn(x) # Batch, sequence length, embedding dimension *3 (1,5,384)
        q,k,v = qkv.split(self.n_embd, dim=2) # splits qkv into 3 tensors along the 3rd dimension so each has shape [1, 5, 128]
        # We view qkv as Batch size, number of self-attention heads, T(sequence length), and number of dimensions per head
        q = q.view(B, T, self.n_head, C // self.n_head).transpose(1,2)
        k = k.view(B, T, self.n_head, C // self.n_head).transpose(1,2)
        v = v.view(B, T, self.n_head, C // self.n_head).transpose(1,2)
        # (B, h, T, hs) * (B, h, hs, T) --> (B, h, hs, hs)
        att = (q @ k.transpose(-2, -1)) * (1.0 / math.sqrt(k.size(-1)))
        att = F.softmax(att, dim=-1) # convert the attention scores into probabilites
        y = att @ v # (B, h, hs, hs) * (B, h, hs, hs) -> (B, nh, T, hs)
        # After computing the attention output for each head, the heads are combined back into the original embedding dimension by reshaping:
        y = y.transpose(1, 2).contiguous().view(B, T, C)
        y = self.c_proj(y)
        return y
#---------------------------------------------------------------------------------------------------

class MLP(nn.Module):
    def __init__(self, n_embd=Config.emb_size):
        """initialize MLP module.
        Args:
            n_embd (int, optional): Embedding dimension.
        """
        super().__init__()
        self.c_fc = nn.Linear(n_embd, 4*n_embd)
        self.gelu = nn.GELU()
        self.c_proj = nn.Linear(4*n_embd, n_embd)
        self.c_proj.NANOGPT_SCALE_INIT = 1

    def forward(self,x):
        """Method for forward pass.
        Args:
            x (tensor): tensor input.
        Returns:
            tensor: output of the MLP module.
        """
        x = self.c_fc(x)
        x = self.gelu(x)
        x = self.c_proj(x)
        return x

#---------------------------------------------------------------------------------------------------


class Block(nn.Module):
    def __init__(self, n_embd=Config.emb_size):
        """initialize Block module.

        Args:
            n_embd (int, optional): Embedding dimension.
        """
        super().__init__()
        self.ln1 =  nn.LayerNorm(n_embd)
        self.attn = SelfAttention(n_embd)
        self.ln2 =  nn.LayerNorm(n_embd)
        self.mlp  = MLP(n_embd)

    def forward(self, x):
        """Method for forward pass.

        Args:
            x (tensor): input tensor.

        Returns:
            tensor: output of the block.
        """
        x = x + self.attn(self.ln1(x)) # residual connections
        x = x + self.mlp (self.ln2(x))
        return x


#---------------------------------------------------------------------------------------------------

class ViT(nn.Module):
    def __init__(self, ch=Config.ch, img_size=Config.img_size, patch_size=Config.patch_size, emb_dim=Config.emb_size, n_layers=Config.n_layers, out_dim=Config.out_dim):
        """initialize ViT module.
        Args:
            ch (int, optional): Number of channels. Defaults to 3.
            img_size (int, optional): Image size. Defaults to 144.
            patch_size (int, optional): Patch size. Defaults to 16.
            emb_dim (int, optional): Embedding dimension. Defaults to 256. 
            n_layers (int, optional): Number of layers. Defaults to 12.
            out_dim (int, optional): Output dimension. Defaults to 10.
        """
        super(ViT, self).__init__()
        self.channels = ch
        self.height = img_size
        self.width = img_size
        self.patch_size = patch_size
        self.n_layers = n_layers

        self.patchEmbedding = PatchEmbedding(
            in_channels=ch,
            patch_size=patch_size,
            emb_size=emb_dim
        )
        num_patches = (img_size // patch_size) ** 2
        self.positional_emb = nn.Parameter(torch.randn(1, num_patches + 1, emb_dim))
        self.cls_token = nn.Parameter(torch.rand(1, 1, emb_dim))

        self.transformer = nn.ModuleList([Block(emb_dim) for _ in range(n_layers)])
        self.ln = nn.LayerNorm(emb_dim)
        self.lm_head = nn.Linear(emb_dim, out_dim, bias=False)

    def forward(self, img):
        """Method for forward pass.

        Args:
            img (tensor): input image tensor.

        Returns:
           logits (tensor): logits.
        """
        x = self.patchEmbedding(img)
        B, T, C = x.shape
        cls_tokens = repeat(self.cls_token, '1 1 d -> b 1 d', b=B)
        x = torch.cat([cls_tokens, x], dim=1)
        x += self.positional_emb[:, :(T + 1)]

        for block in self.transformer:
            x = block(x)

        x = self.ln(x)
        logits = self.lm_head(x[:, 0])  # [CLS] token output for classification
        return logits

#---------------------------------------------------------------------------------------------------

def load_split_data(dataset, split_ratio=0.8):
    """Load and split the dataset into training and validation sets.

    Args:
        dataset (torchvision.dataset): The dataset object.
        split_ratio (float, optional): Ratio to split the dataset. Defaults to 0.8.

    Returns:
        torchvision.dataset: Training dataset.
    """
    total_samples = len(dataset)
    training_amount = int(split_ratio * total_samples)
    validation_amount = total_samples - training_amount

    # Split the dataset into training and validation sets
    train_dataset, val_dataset = random_split(dataset, [training_amount, validation_amount])

    return train_dataset, val_dataset

def calculate_validation_loss(model, val_loader, criterion, device):
    """Calculate the average loss on the validation set.

    Args:
        model (nn.Module): The model to evaluate.
        val_loader (DataLoader): The validation data loader.
        criterion (nn.Module): The loss function.
        device (str): The device to run the model on.

    Returns:
        float: The average loss on the validation set.
    """
    model.eval()  # Set the model to evaluation mode
    running_loss = 0.0
    total_samples = 0

    with torch.no_grad():  # No need to track gradients for validation
        for inputs, targets in val_loader:
            inputs, targets = inputs.to(device), targets.to(device)
            outputs = model(inputs)
            loss = criterion(outputs, targets)
            running_loss += loss.item() * inputs.size(0)
            total_samples += inputs.size(0)

    avg_loss = running_loss / total_samples
    return avg_loss


def inference_in_batches(X, batch_size):
    """Run inference on the input data in batches.

    Args:
        X (tensor): The input data.
        batch_size (int): The batch size.

    Returns:
       predicted_classes (tensor): The predicted classes.
       probabilities (tensor): The predicted probabilities.
    """
    model.eval()  # Set model to evaluation mode
    predicted_classes = []
    probabilities = []

    num_samples = X.size(0)

    with torch.no_grad():
        for start in range(0, num_samples, batch_size):
            end = min(start + batch_size, num_samples)
            batch_X = X[start:end]

            logits = model(batch_X)
            probs = torch.softmax(logits, dim=1)
            predicted_class = torch.argmax(probs, dim=1)

            predicted_classes.append(predicted_class)
            probabilities.append(probs)

    # Concatenate results from all batches
    predicted_classes = torch.cat(predicted_classes, dim=0)
    probabilities = torch.cat(probabilities, dim=0)

    return predicted_classes, probabilities


#-----------------------------Training Loop----------------------------------------------

train_dataset, val_dataset = load_split_data(dataset)

train_dataloader = DataLoader(train_dataset, batch_size=32, shuffle=True)
val_loader = DataLoader(val_dataset, batch_size=32, shuffle=False)


# Model, optimizer, criterion
model = ViT()
optimizer = torch.optim.Adam(model.parameters(), lr=1e-4)
criterion = nn.CrossEntropyLoss()

# Parameters
epochs = 10  # Number of epochs to run
loss_per_epoch = []
val_loss_per_epoch = []

# Scheduler for learning rate decay (decay every 2 epochs for example)
scheduler = CosineAnnealingLR(optimizer, T_max=epochs)

# Create a directory to save models
model_dir = 'saved_models_L2'
os.makedirs(model_dir, exist_ok=True)

# Prepare model for training
model.train()

# Loop over epochs
for epoch in range(epochs):
    epoch_loss = 0.0  # Accumulate loss for the epoch
    num_batches = 0   # Track the number of batches in each epoch

    print(f"Epoch [{epoch+1}/{epochs}]")

    # Loop over batches in the training data
    for Xb, Yb in train_dataloader:

        # Move data to GPU if available
        if torch.cuda.is_available():
            Xb, Yb = Xb.cuda(), Yb.cuda()
            model = model.cuda()

        # Forward pass
        logits = model(Xb)
        loss = criterion(logits, Yb)

        # Backward pass
        optimizer.zero_grad()  # Clear the gradients
        loss.backward()  # Backpropagation
        optimizer.step()  # Update the weights

        # Accumulate the total loss for this epoch
        epoch_loss += loss.item()
        num_batches += 1

    # Calculate the average loss for the epoch
    avg_epoch_loss = epoch_loss / num_batches
    loss_per_epoch.append(avg_epoch_loss)

    # Calculate validation loss
    avg_val_loss = calculate_validation_loss(model, val_loader, criterion, "cuda")
    val_loss_per_epoch.append(avg_val_loss)

    # Print the average loss for this epoch
    print(f"Epoch [{epoch+1}/{epochs}], Average Loss: {avg_epoch_loss:.4f}")

    # Step the scheduler after each epoch
    scheduler.step()


    if epoch % 5 == 0:
      # Save the model checkpoint
      model_path = os.path.join(model_dir, f'vit_model_epoch_{epoch+1}.pth')
      torch.save({
          'epoch': epoch + 1,
          'model_state_dict': model.state_dict(),
          'optimizer_state_dict': optimizer.state_dict(),
          'scheduler_state_dict': scheduler.state_dict(),
          'loss': avg_epoch_loss,
      }, model_path)

      print(f"Model saved at {model_path}")


#---------------------------------------------------------------------------------------------------

plt.figure(figsize=(10, 6))
plt.plot(range(1, epochs + 1), loss_per_epoch, marker='o', linestyle='-', color='b')
plt.plot(range(1, epochs + 1), val_loss_per_epoch, marker='o', linestyle='-', color='r')
plt.xlabel('Epoch')
plt.ylabel('Average Loss')
plt.title('Training Loss per Epoch')
plt.grid(True)
plt.show()

batch_size = 32
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
num_samples = len(val_dataset)
Xtest = torch.zeros((num_samples, 3, 144, 144)).to(device)
Ytest = torch.zeros(num_samples, dtype=torch.long).to(device)


for i in range(num_samples):
    img, target = dataset[i]
    Xtest[i] = img.to(device)  # Store the image on GPU
    Ytest[i] = torch.tensor(target, dtype=torch.long).to(device)  # Convert target to tensor and move to GPU


# Run inference
predicted_class, probs = inference_in_batches(Xtest, batch_size)
print(predicted_class[:20])
target = torch.tensor(target, dtype=torch.long)
print(Ytest[:20])

print((predicted_class == Ytest).float().mean())

Ytest_np = Ytest.cpu().numpy()
predicted_class_np = predicted_class.cpu().numpy()

num_classes = 10
cm = confusion_matrix(Ytest_np, predicted_class_np, labels=list(range(num_classes)))

# Plot the confusion matrix
plt.figure(figsize=(10, 8))
sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', xticklabels=list(range(num_classes)), yticklabels=list(range(num_classes)))
plt.xlabel('Predicted Label')
plt.ylabel('True Label')
plt.title('Confusion Matrix')
plt.show()

