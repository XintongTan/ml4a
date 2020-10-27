import os
import csv
import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from tqdm import tqdm
from scipy.io import loadmat
from distutils.version import LooseVersion

from ..utils import downloads
from . import submodules


with submodules.import_from('semantic-segmentation-pytorch'):
    from mit_semseg.dataset import TestDataset
    from mit_semseg.models import ModelBuilder, SegmentationModule
    from mit_semseg.utils import colorEncode, find_recursive, setup_logger
    from mit_semseg.lib.nn import user_scattered_collate, async_copy_to
    from mit_semseg.lib.utils import as_numpy
    from mit_semseg.config import cfg

    
    

model = None


# w.i.p



def visualize_result(data, pred, cfg):
    (img, info) = data

    # print predictions in descending order
    pred = np.int32(pred)
    pixs = pred.size
    uniques, counts = np.unique(pred, return_counts=True)
    print("Predictions in [{}]:".format(info))
    for idx in np.argsort(counts)[::-1]:
        name = names[uniques[idx] + 1]
        ratio = counts[idx] / pixs * 100
        if ratio > 0.1:
            print("  {}: {:.2f}%".format(name, ratio))

    # colorize prediction
    pred_color = colorEncode(pred, colors).astype(np.uint8)

    # aggregate images and save
    im_vis = np.concatenate((img, pred_color), axis=1)
    return im_vis

#     img_name = info.split('/')[-1]
#     Image.fromarray(im_vis).save(
#         os.path.join(cfg.TEST.result, img_name.replace('.jpg', '.png')))




def test_imgs(segmentation_module, loader, gpu):
    segmentation_module.eval()

    pbar = tqdm(total=len(loader))
    for batch_data in loader:
        # process data
        batch_data = batch_data[0]
        segSize = (batch_data['img_ori'].shape[0],
                   batch_data['img_ori'].shape[1])
        img_resized_list = batch_data['img_data']

        with torch.no_grad():
            scores = torch.zeros(1, cfg.DATASET.num_class, segSize[0], segSize[1])
            scores = async_copy_to(scores, gpu)

            for img in img_resized_list:
                feed_dict = batch_data.copy()
                feed_dict['img_data'] = img
                del feed_dict['img_ori']
                del feed_dict['info']
                feed_dict = async_copy_to(feed_dict, gpu)

                # forward pass
                pred_tmp = segmentation_module(feed_dict, segSize=segSize)
                scores = scores + pred_tmp / len(cfg.DATASET.imgSizes)

            _, pred = torch.max(scores, dim=1)
            pred = as_numpy(pred.squeeze(0).cpu())

        # visualization
        im_vis = visualize_result(
            (batch_data['img_ori'], batch_data['info']),
            pred,
            cfg
        )

        pbar.update(1)
        
        return im_vis







def setup():

    global names, colors
    
    # local repo files
    root = submodules.get_submodules_root('semantic-segmentation-pytorch')
    color_path = os.path.join(root, 'data/color150.mat')
    data_path = os.path.join(root, 'data/object150_info.csv')
    cfg_path = os.path.join(root, 'config/ade20k-resnet50dilated-ppm_deepsup.yaml')

    colors = loadmat(color_path)['colors']
    names = {}
    with open(data_path) as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            names[int(row[0])] = row[5].split(";")[0]

    # downloadable files
    ml4a_dl_root = downloads.get_ml4a_downloads_folder()
    ssp_dl_root = 'semantic-segmentation-pytorch/ade20k-resnet50dilated-ppm_deepsup'
    model_path = os.path.join(ml4a_dl_root, ssp_dl_root)
    print("THE MODEL IS HERE: ", model_path)
    
    # download model
    encoder = downloads.download_data_file(
        'http://sceneparsing.csail.mit.edu/model/pytorch/ade20k-resnet50dilated-ppm_deepsup/encoder_epoch_20.pth', 
        '%s/encoder_epoch_20.pth' % ssp_dl_root)
    
    decoder = downloads.download_data_file(
        'http://sceneparsing.csail.mit.edu/model/pytorch/ade20k-resnet50dilated-ppm_deepsup/decoder_epoch_20.pth', 
        '%s/decoder_epoch_20.pth' % ssp_dl_root)
    
    
    
    
    
    
    gpu = 0
    opts = ['DIR', model_path, 'TEST.result', './', 'TEST.checkpoint', 'epoch_20.pth']

    cfg.merge_from_file(cfg_path)
    cfg.merge_from_list(opts)   # is this needed?

    cfg.MODEL.arch_encoder = cfg.MODEL.arch_encoder.lower()
    cfg.MODEL.arch_decoder = cfg.MODEL.arch_decoder.lower()

    # absolute paths of model weights
    cfg.MODEL.weights_encoder = os.path.join(
        cfg.DIR, 'encoder_' + cfg.TEST.checkpoint)
    cfg.MODEL.weights_decoder = os.path.join(
        cfg.DIR, 'decoder_' + cfg.TEST.checkpoint)

    assert os.path.exists(cfg.MODEL.weights_encoder) and \
        os.path.exists(cfg.MODEL.weights_decoder), "checkpoint does not exitst!"


    imgs = ['../../../neural_style/images/inputs/frida_kahlo.jpg']

    cfg.list_test = [{'fpath_img': x} for x in imgs]

    # MAIN
    torch.cuda.set_device(gpu)

    # Network Builders
    net_encoder = ModelBuilder.build_encoder(
        arch=cfg.MODEL.arch_encoder,
        fc_dim=cfg.MODEL.fc_dim,
        weights=cfg.MODEL.weights_encoder)
    net_decoder = ModelBuilder.build_decoder(
        arch=cfg.MODEL.arch_decoder,
        fc_dim=cfg.MODEL.fc_dim,
        num_class=cfg.DATASET.num_class,
        weights=cfg.MODEL.weights_decoder,
        use_softmax=True)

    crit = nn.NLLLoss(ignore_index=-1)

    segmentation_module = SegmentationModule(net_encoder, net_decoder, crit)

    # Dataset and Loader
    dataset_test = TestDataset(
        cfg.list_test,
        cfg.DATASET)
    loader_test = torch.utils.data.DataLoader(
        dataset_test,
        batch_size=cfg.TEST.batch_size,
        shuffle=False,
        collate_fn=user_scattered_collate,
        num_workers=5,
        drop_last=True)

    segmentation_module.cuda()


    
    
    
    
    

    # Main loop
    return test_imgs(segmentation_module, loader_test, gpu)

#    print('Inference done!')


#     global model
#     model_directory = downloads.download_from_gdrive(
#         '1TQf-LyS8rRDDapdcTnEgWzYJllPgiXdj', 
#         'photosketch/pretrained',
#         zip_file=True)
#     opt = {}
#     opt = SimpleNamespace(**opt)
#     opt.nThreads = 1
#     opt.batchSize = 1
#     opt.serial_batches = True
#     opt.no_flip = True 
#     opt.name = model_directory
#     opt.checkpoints_dir = '.'
#     opt.model = 'pix2pix'
#     opt.which_direction = 'AtoB'
#     opt.norm = 'batch'
#     opt.input_nc = 3
#     opt.output_nc = 1
#     opt.which_model_netG = 'resnet_9blocks'
#     opt.no_dropout = True
#     opt.isTrain = False
#     opt.use_cuda = True
#     opt.ngf = 64
#     opt.ndf = 64
#     opt.init_type = 'normal'
#     opt.which_epoch = 'latest'
#     opt.pretrain_path = model_directory
#     model = create_model(opt)
#     return model


def run(img):
    print('go')