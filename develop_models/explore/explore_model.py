# -*- coding: utf-8 -*-
# License: BSD
# Author: Sasank Chilamkurthy
# This model tunes the learning rate of resnet and explores how this affects accuracy
from __future__ import print_function, division

import torch
import torch.nn as nn
from torch import optim, cuda
from torch.optim import lr_scheduler
import numpy as np
from torchvision import datasets, models, transforms
import matplotlib.pyplot as plt
import time
import os
import pandas as pd
from timeit import default_timer as timer
import tempfile
import sys
import copy
print(__file__)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
print(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from load_data import ForamDataSet
plt.ion()   # interactive mode
train_on_gpu = torch.cuda.is_available()

# Whether to train on a gpu
train_on_gpu = cuda.is_available()
print('Train on gpu: {train_on_gpu}'.format(train_on_gpu=train_on_gpu))
multi_gpu = False
# Number of gpus
if train_on_gpu:
    gpu_count = cuda.device_count()
    print('{gpu_count} gpus detected.'.format(gpu_count=gpu_count))
device = torch.device("cuda:{i}".format(i=os.environ["CUDA_VISIBILE_DEVICES"]) if torch.cuda.is_available() else "cpu")

data_transforms = {
    'train': transforms.Compose([
        transforms.ToPILImage(),
        transforms.RandomResizedCrop(224),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ]),
    # val does not use augmentation
    'val': transforms.Compose([
        transforms.ToPILImage(),
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ]),
    # test does not use augmentation
    'test': transforms.Compose([
        transforms.ToPILImage(),
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ]),
}

######################################################################
# Training the model
# ------------------
#
# Now, let's write a general function to train a model. Here, we will
# illustrate:
#
# -  Scheduling the learning rate
# -  Saving the best model
#
# In the following, parameter ``scheduler`` is an LR scheduler object from
# ``torch.optim.lr_scheduler``.


def train_model(model, criterion, optimizer, scheduler, num_epochs=25):
    since = time.time()
    best_model_wts = copy.deepcopy(model.state_dict())
    best_acc = 0.0
    history = []

    for epoch in range(num_epochs):
        print('Epoch {}/{}'.format(epoch, num_epochs - 1))
        print('-' * 10)

        # Each epoch has a training and validation phase
        for phase in ['train', 'val']:
            if phase == 'train':
                scheduler.step()
                model.train()  # Set model to training mode
            else:
                model.eval()   # Set model to evaluate mode

            running_loss = 0.0
            running_corrects = 0

            # Iterate over data.
            for inputs, labels in dataloaders[phase]:
                inputs = inputs.to(device)
                labels = labels.to(device)
                # zero the parameter gradients. what and why do we need this
                optimizer.zero_grad()

                # forward
                # track history if only in train
                with torch.set_grad_enabled(phase == 'train'):
                    outputs = model(inputs)
                    _, preds = torch.max(outputs, 1)
                    loss = criterion(outputs, labels)

                    # backward + optimize only if in training phase
                    if phase == 'train':
                        loss.backward()
                        optimizer.step()

                # statistics
                running_loss += loss.item() * inputs.size(0)
                running_corrects += torch.sum(preds == labels.data)

            epoch_loss = running_loss / dataset_sizes[phase]
            epoch_acc = running_corrects.double() / dataset_sizes[phase]
            history.append([phase, epoch_loss, epoch_acc])
            print('{} Loss: {:.4f} Acc: {:.4f}'.format(
                phase, epoch_loss, epoch_acc.item()))

            # deep copy the model
            if phase == 'val' and epoch_acc > best_acc:
                best_acc = epoch_acc
                best_model_wts = copy.deepcopy(model.state_dict())
        print()
    time_elapsed = time.time() - since
    print('Training complete in {:.0f}m {:.0f}s'.format(
        time_elapsed // 60, time_elapsed % 60))
    print('Best val Acc: {:4f}'.format(best_acc))

    # load best model weights
    model.load_state_dict(best_model_wts)
    torch.save(model.state_dict(), './resnet18-foram.pth')
    history = pd.DataFrame(
        history,
        columns=['phase', 'epoch_loss', 'epoch_acc'])
    return model, history


def create_model(model_type, classes, lr):
    criteria = {}
    if model_type == 'resnet18':
        model = models.resnet18(pretrained=True)
        num_ftrs = model.fc.in_features
        model.fc = nn.Linear(num_ftrs, len(classes)) # resets finaly layer
        criterion = nn.CrossEntropyLoss()
        optimizer = optim.SGD(model.parameters(), lr=lr, momentum=0.9)
        exp_lr_scheduler = lr_scheduler.StepLR(optimizer, step_size=7, gamma=0.1)

    if model_type == 'resnet34':
        model = models.resnet34(pretrained=True)
        num_ftrs = model.fc.in_features
        model.fc = nn.Linear(num_ftrs, len(classes)) # resets finaly layer
        criterion = nn.CrossEntropyLoss()
        optimizer = optim.SGD(model.parameters(), lr=lr, momentum=0.9)
        exp_lr_scheduler = lr_scheduler.StepLR(optimizer, step_size=7, gamma=0.1)

    if model_type == 'resnet18_partial':
        model = models.resnet18(pretrained=True)
        for param in model.parameters():    # unfreeeze the 4th and 5th layers
            if 512 in param.shape:
                break
            param.requires_grad = False
        num_ftrs = model.fc.in_features
        model.fc = nn.Linear(num_ftrs, len(classes)) # resets finaly layer
        criterion = nn.CrossEntropyLoss()
        optimizer = optim.SGD(model.parameters(), lr=lr, momentum=0.9)
        exp_lr_scheduler = lr_scheduler.StepLR(optimizer, step_size=7, gamma=0.1)

    if train_on_gpu:
        model = model.to(device)

    if multi_gpu:
        model = nn.DataParallel(model)
    criteria['model'] = model
    criteria['optimizer'] = optimizer
    criteria['criterion'] = criterion
    criteria['scheduler'] = exp_lr_scheduler
    model.idx_to_class = {num:species for num,species in enumerate(classes)}
    model, history = train_model(**criteria)
    return model, history


def accuracy(output, target, topk=(1, )):
    """
    Compute the topk accuracy(s)
    target: the correct labelled answer
    """
    if train_on_gpu:
        output = output.to(device)
        target = target.to(device)

    with torch.no_grad():
        maxk = max(topk)
        batch_size = target.size(0)

        # Find the predicted classes and transpose
        _, pred = output.topk(k=maxk, dim=1, largest=True, sorted=True)
        pred = pred.t()
        # Determine predictions equal to the targets
        correct = pred.eq(target.view(1, -1).expand_as(pred))
        res = []

        # For each k, find the percentage of correct
        for k in topk:
            correct_k = correct[:k].view(-1).float().sum(0, keepdim=True)
            res.append(correct_k.mul_(100.0 / batch_size).item())
        return res


def overall_accuracy(model, test_loader):
    model.eval()
    with torch.no_grad():
        counter = 0
        result = 0
        # Testing loop
        for data, targets in test_loader:
            if train_on_gpu:
                data, targets = data.to(device), targets.to(device)
            # Raw model output
            result += accuracy(model(data), targets)[0]
            counter += 1
    return result/counter

data_dir = '../training-images'
image_datasets = {}
all_lr = [0.0005+(0.0001*i) for i in range(1,11)] # learning rates to test
# all_lr += [0.001*i for i in range(1,6)]
# all_lr += [0.01*i for i in range(1,6)]
# all_lr += [0.1*i for i in range(1,6)]

record = []
arrangement = [[2,3,1,0]]
for num, arr in enumerate(arrangement):
    order = {}
    with tempfile.TemporaryDirectory() as dirpath:
        order['test'] = arr[0]
        order['val'] = arr[1]
        order['train'] = arr[2:]
        if len(order['train']) > 1:
            temp_frame = pd.concat([pd.read_csv('../data-csv/file{num}.csv'.format(num=i))
                                    for i in order['train']])
            temp_frame.to_csv(os.path.join(dirpath, 'train.csv'), encoding='utf-8', index=False)
        image_datasets['train'] = ForamDataSet(csv_file=os.path.join(dirpath, 'train.csv'),
                                               root_dir=data_dir,
                                               master_file='../data-csv/file0.csv',
                                               transform=data_transforms['train'])
        image_datasets['val'] = ForamDataSet(csv_file='../data-csv/file{i}.csv'.format(i=order['val']),
                                             root_dir=data_dir,
                                             master_file='../data-csv/file0.csv',
                                             transform=data_transforms['val'])
        image_datasets['test'] = ForamDataSet(csv_file='../data-csv/file{i}.csv'.format(i=order['test']),
                                              root_dir=data_dir,
                                              master_file='../data-csv/file0.csv',
                                              transform=data_transforms['test'])                                     
        dataloaders = {x: torch.utils.data.DataLoader(image_datasets[x], batch_size=4,
                                                      shuffle=True, num_workers=4)
                       for x in ['train', 'val', 'test']}
        dataset_sizes = {x: len(image_datasets[x]) for x in ['train', 'val', 'test']}
        classes = image_datasets['train'].labels
        for lr in all_lr:
            model, _ = create_model('resnet18_partial', classes, lr)    # training starts
            checkpoint = {
                'idx_to_class': model.idx_to_class,
            }
            if multi_gpu:
                checkpoint['classifier'] = model.fc
                checkpoint['state_dict'] = model.module.state_dict()
            else:
                checkpoint['classifier'] = model.fc
                checkpoint['state_dict'] = model.state_dict()

            # Add the optimizer
            try:
                checkpoint['optimizer'] = model.optimizer
                checkpoint['optimizer_state_dict'] = model.optimizer.state_dict()
            except Exception as e:
                print(str(e))
            # torch.save(model.state_dict(), './resnet18{i}.pth'.format(i=num))     # save model here
            acc = overall_accuracy(model, dataloaders['test'])
            print('accuracy is:', acc)
            record.append([lr, acc])

record = pd.DataFrame(
    record,
    columns=['learning_rate', 'overall_accuracy'])
record.to_csv('./record1.csv')