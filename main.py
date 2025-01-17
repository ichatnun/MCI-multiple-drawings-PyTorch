import pdb, os, sys, argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import torch
import torchvision

import lightning as pl # conda install lightning -c conda-forge
from lightning.pytorch.loggers import CSVLogger
from lightning.pytorch.callbacks import ModelCheckpoint

from models.get_model import get_model
from dataloader.get_dataloaders import get_dataloaders
from utils.utils import make_exp_name, test_dataloader, test_model, save_evaluation

def run_one_seed(args, 
                 dataset_name, 
                 healthy_threshold, 
                 class_list, 
                 num_classes, 
                 random_seed,
                 task_list,
                 results_exp_dir):

    results_dir = make_exp_name(os.path.join(results_exp_dir, str(random_seed)))
    os.makedirs(results_dir, exist_ok=True)
    
    ## Detect if we have a GPU available
    if torch.cuda.is_available():
        num_gpus = torch.cuda.device_count() 
        device = torch.device(f"cuda:{args.gpu_id}")
        gpu_list = [args.gpu_id]
        print(f"device: {torch.cuda.get_device_name(args.gpu_id)}")
    else:
        device = torch.device("cpu")

    ## Generate dataloders: dataloader_dict.keys -> 'train', 'val', 'test'
    dataloader_dict, label_distribution_train = get_dataloaders(args.use_pretrained_weight, 
                                                                args.label_type, 
                                                                args.val_fraction, 
                                                                args.test_fraction, 
                                                                random_seed,
                                                                args.batch_size, 
                                                                args.num_workers, 
                                                                dataset_name, 
                                                                healthy_threshold,
                                                                task_list, 
                                                                results_dir)
        
    ## Try getting a batch from the test Dataloader
    if args.test_dataloader:
        test_dataloader(dataloader_dict['test'], 
                        results_dir, 
                        args.batch_size, 
                        task_list)
        
    # Define the loss function
    if args.label_type in ['hard', 'soft']:
        if args.add_weight_to_loss:
            loss_weight = 1/label_distribution_train
            loss_weight = loss_weight/np.sum(loss_weight)
            loss_fn = torch.nn.CrossEntropyLoss(weight=torch.Tensor(loss_weight), reduction='mean')
        else:
            loss_fn = torch.nn.CrossEntropyLoss(reduction='mean')
    elif args.label_type == 'raw':
        num_classes = 1
        loss_fn = torch.nn.MSELoss(reduction='mean')
                
    # Create a ModuleDict model
    model = get_model(args.model_name, 
                      num_classes, 
                      task_list, 
                      args.use_pretrained_weight, 
                      args.freeze_backbone)

    # Define the LightningModule
    class LitVGG16(pl.LightningModule):
        
        def __init__(self, model, loss_fn):
            super().__init__()
            self.model = model
            self.loss_fn = loss_fn
            self.softmax = torch.nn.Softmax(dim=1)

        def training_step(self, batch, batch_idx):
            x, y = batch
            logits_predicted = self.model(x) # Without softmax
                
            loss = self.loss_fn(logits_predicted, y)
            
            # Log results
            self.log("train_loss", loss)
            
            return loss
        
        def forward(self, x):
            logits_predicted = self.model(x) # Without softmax
            return self.softmax(logits_predicted)
        
        def validation_step(self, batch, batch_idx):
            x, y = batch
            logits_predicted = self.model(x) # Without softmax

            loss = self.loss_fn(logits_predicted, y)

            # Log results
            self.log("val_loss", loss)

            return loss

        def configure_optimizers(self):
            return torch.optim.SGD(self.model.parameters(), 
                                   lr=0.001, 
                                   momentum=0.9)

    # Create the model
    modelLit = LitVGG16(model, loss_fn)

    # Prepare logger
    logger = CSVLogger(save_dir=results_dir)
    
    # Prepare callbacks
    checkpoint_callback = ModelCheckpoint(dirpath=results_dir, 
                                          filename='{epoch}-{val_loss:.2f}', 
                                          monitor='val_loss',
                                          mode='min',
                                          save_top_k=1, 
                                          every_n_epochs=1)
    
    # Train the model
    trainer = pl.Trainer(max_epochs=args.num_epochs, 
                         logger=logger,
                         callbacks=[checkpoint_callback],
                         devices=gpu_list, 
                         log_every_n_steps=dataloader_dict['train'].__len__(),
                         accelerator="gpu")

    trainer.fit(model=modelLit, 
                train_dataloaders=dataloader_dict['train'], 
                val_dataloaders=dataloader_dict['val'])

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        
    # Load the best model
    trained_model = LitVGG16.load_from_checkpoint(checkpoint_callback.best_model_path, 
                                                  model=model, 
                                                  loss_fn=loss_fn)
    
    # Test the model
    labels_true, probs_predicted = test_model(trained_model, 
                                              dataloader_dict['test'],
                                              device)
    
    # Save evaluation metrics    
    save_evaluation(labels_true,
                    probs_predicted,
                    results_dir, 
                    class_list)
    
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        

if __name__ == "__main__":
    
    print(f"PyTorch Version: {torch.__version__}")
    print(f"Torchvision Version: {torchvision.__version__}")

    ## Arguments
    parser = argparse.ArgumentParser()
    
    # Experimental setup
    parser.add_argument('--num_seeds', default=10, type=int)
    parser.add_argument('--val_fraction', default=0.15, type=float)
    parser.add_argument('--test_fraction', default=0.15, type=float)
    parser.add_argument('--num_epochs', default=100, type=int)
    parser.add_argument('--batch_size', default=64, type=int)
    parser.add_argument('--exp_name', default='', type=str)
    parser.add_argument('--gpu_id', default=0, type=int)
    
    # Model config
    parser.add_argument('--model_name', 
                        default='vgg16', 
                        type=str, 
                        help="Available options: 'vgg16', 'conv-att'")
    parser.add_argument('--config_file', default='', type=str)
    parser.add_argument('--use_pretrained_weight', default=False, action='store_true')
    parser.add_argument('--freeze_backbone', default=False, action='store_true')
    parser.add_argument('--add_weight_to_loss', default=False, action='store_true')
    
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
    parser.add_argument('--num_workers', default=8, type=int)
    
    ## Processing the arguments
    args = parser.parse_args()
 
    # Check val and test fractions
    if args.val_fraction + args.test_fraction >= 1:
        print('Invalid training fraction')
        sys.exit(1)
        
    # Check if at least one task is specified
    if not (args.include_clock or args.include_copy or args.include_trail):
        print('No valid task specified')
        sys.exit(1)
     
    # Create task_list
    task_list = []
    if args.include_clock:
        task_list.append('clock')
    if args.include_copy:
        task_list.append('copy')
    if args.include_trail:
        task_list.append('trail')
        
    # Create a dictionary to store additional info    
    dataset_name = 'multiDrawingMCI'
    idx2class_dict = {'0': 'control', '1': 'mci'}
    healthy_threshold = 25 # MoCA score of >= 25-> healthy
    class_list = [idx2class_dict[key] for key in idx2class_dict.keys()]
    num_classes = len(idx2class_dict.keys())
    
    # Create 'results' folder (Ex. results/multidrawingmci/EXP_...)
    if len(task_list) == 3:
        task_str = 'all'
    else:
        task_str = task_list[0]
        for curr_task in task_list[1:]:
            task_str += f"_{curr_task}"
             
    if args.exp_name:
        results_exp_dir = os.path.join('results', 
                                       f"{args.exp_name}_{task_str}",  
                                       args.label_type, 
                                       args.model_name)
    else:
        results_exp_dir = os.path.join('results', 
                                       task_str,
                                       args.label_type, 
                                       args.model_name)

    os.makedirs(results_exp_dir, exist_ok=True)

    num_seeds = max(1, args.num_seeds)
    list_of_seeds = np.arange(1024, 1024+num_seeds)
    for idx_seed, curr_seed in enumerate(list_of_seeds):
        run_one_seed(args, 
                     dataset_name, 
                     healthy_threshold, 
                     class_list, 
                     num_classes, 
                     curr_seed,
                     task_list,
                     results_exp_dir)
    print(f"Done: {idx_seed+1}/{num_seeds}")