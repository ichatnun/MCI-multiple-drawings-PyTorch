import pdb, os, sys, argparse
import numpy as np
import matplotlib.pyplot as plt

import torch
import torch.optim as optim
import torch.nn as nn

import pandas as pd

import torchvision
from torchvision import datasets, models, transforms
from torchvision.models import vgg16, VGG16_Weights

from dataloader.getDataloaders import getDataloaders
from utils.utils import make_exp_name, save_evaluation, test_model, testDataloader
from train.train_single_input import train_model
from train.utils_train import SoftLabelCrossEntropyLoss


if __name__ == "__main__":
    
    print(f"PyTorch Version: {torch.__version__}")
    print(f"Torchvision Version: {torchvision.__version__}")

    ## Arguments
    parser = argparse.ArgumentParser()
    
    # Experimental setup
    parser.add_argument('--random_seed', default=777, type=int)
    parser.add_argument('--val_fraction', default=0.15, type=float)
    parser.add_argument('--test_fraction', default=0.15, type=float)
    parser.add_argument('--num_epochs', default=100, type=int)
    parser.add_argument('--exp_name', default='', type=str)
    
    # Model config
    parser.add_argument('--model_name', default='vgg16', type=str)
    parser.add_argument('--config_file', default='', type=str)
    parser.add_argument('--use_pretrained_weight', default=False, action='store_true')
    
    # Data and labels
    parser.add_argument('--include_clock', default=False, action='store_true')
    parser.add_argument('--include_copy', default=False, action='store_true')
    parser.add_argument('--include_trail', default=False, action='store_true')
    parser.add_argument('--label_type', 
                        default='soft', 
                        type=str, 
                        help="Options: 'raw', 'hard', 'soft'")
    parser.add_argument('--test_dataloader', 
                        default=False, 
                        action='store_true',
                        help="Set to True to get a sample batch (to test out the dataloader)")
    
    ## Processing the arguments
    args = parser.parse_args()
    
    # Create a dictionary to store additional info
    add_info = {'num_classes': 2,
                'idx2class_dict': {'0': 'control', '1': 'mci'},
               'healthy_threshold': 25, # MoCA score of >= 25-> healthy
               'dataset_name': 'multiDrawingMCI',
               'batch_size': 64}
    add_info['class_list'] = [add_info['idx2class_dict'][key] for key in ['0', '1']]
    
    # Create 'results' folder (Ex. results/multidrawingmci/EXP_...)
    add_info['results_dir'] = os.path.join('results', make_exp_name(args.exp_name))
    os.makedirs(add_info['results_dir'], exist_ok=False)
    os.makedirs(os.path.join(add_info['results_dir'], 'temp'),
                exist_ok=False) # Store temp info during training
    
    # Check val and test fractions
    if args.val_fraction + args.test_fraction >= 1:
        print('Invalid training fraction')
        sys.exit(1)
        
    # Check if at least one task is specified
    if not (args.include_clock or args.include_copy or args.include_trail):
        print('No valid task specified')
        sys.exit(1)

    # Create task_list
    add_info['task_list'] = []
    if args.include_clock:
        add_info['task_list'].append('clock')
    if args.include_copy:
        add_info['task_list'].append('copy')
    if args.include_trail:
        add_info['task_list'].append('trail')
        
    ## Detect if we have a GPU available
    add_info['device'] = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print(f"device: {add_info['device']}")
    
    ## Generate dataloders: dataloader_dict.keys -> 'train', 'val', 'test'
    dataloader_dict = getDataloaders(args, add_info)
    
    ## Try getting a batch from the test Dataloader
    if args.test_dataloader:
        testDataloader(dataloader_dict['test'], 
                       add_info['results_dir'], 
                       add_info['batch_size'], 
                       add_info['task_list'])
        
    pdb.set_trace()
        
    # Define the loss function
    if args.label_type == 'soft':
        loss_fn = SoftLabelCrossEntropyLoss(reduction='mean')
    elif args.label_type == 'raw':
        add_info['num_classes'] = 1
    else:
        loss_fn = torch.nn.CrossEntropyLoss(reduction='mean')        
        
#     ## Create our model
#     model = vgg16(weights=VGG16_Weights.IMAGENET1K_V1)
#     num_final_features = model.classifier[-1].in_features
#     model.classifier[-1] = nn.Linear(num_final_features, add_info['num_classes'])
    
#     for param in model.parameters():
#         param.requires_grad = True

#     optimizer = torch.optim.SGD(model.parameters(), lr=0.001, momentum=0.9)
    
#     ## Train the model
#     model = model.to(add_info['device'])
#     trained_model, history = train_model(model,
#                                          dataloader_dict,
#                                          loss_fn,
#                                          optimizer,
#                                          num_epochs=args.num_epochs,
#                                          device=add_info['device'],
#                                          results_dir=add_info['results_dir'],
#                                          task=add_info['task_list'])
    
    
#     ## Test the model
#     labels_true_all,labels_predicted_all, proba_predicted_all = test_model(trained_model,
#                                                  dataloader_dict['test'], 
#                                                         add_info['task_list'], 
#                                                         add_info['device'])

#     best_val_loss = np.max(history['val_loss'])
    
#     save_evaluation(labels_true_all,
#                     labels_predicted_all, 
#                     proba_predicted_all,
#                     add_info['results_dir'], 
#                     add_info['class_list'],
#                     best_val_loss)