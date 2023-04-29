# Created by Churong Ji at 4/27/23
from model import *
from utils import *
from network import *
import torch
import socket
from torch import optim
import time

lr = 5e-2
retrain_num_epochs = 1
retrain_batch_size = 10
retrain_counter = 0
# options: ['cpu', 'gpu']
device = 'cpu'
updated_model_path = 'yolo_updated_detector.pt'

# define the server socket locally
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind((socket.gethostname(), 1234))
s.listen(5)
clientsocket = None


def serverReceiveImg():
    # should be a BLOCKING function if not enough image received
    # returns batch img and annotation, assume img already normalized
    while True:
        clientsocket, address = s.accept()
        lis = receive_imgs(clientsocket)
        break
    # print("start processing")
    image_batch_lis = [item[0] for item in lis]
    box_batch_lis = [item[1] for item in lis]
    w_batch_lis = [item[2].item() for item in lis]
    h_batch_lis = [item[3].item() for item in lis]
    imgid_batch_lis = [item[4] for item in lis]
    image_batch = torch.cat(image_batch_lis, 0)
    box_batch = torch.cat(box_batch_lis)
    print(image_batch_lis[0].shape)
    print(box_batch_lis[0].shape)

    w_batch = torch.tensor(w_batch_lis)
    h_batch = torch.tensor(h_batch_lis)
    img_id_list = imgid_batch_lis
    print("img batch shape", image_batch.shape)
    print("box batch shape", box_batch.shape)
    print("w_batch shape", w_batch.shape)
    print("h_batch shape", h_batch.shape)
    # image_batch = torch.zeros(retrain_batch_size, 3, 224, 224)
    # box_batch = torch.zeros(retrain_batch_size, 6, 5)
    # w_batch = torch.zeros(retrain_batch_size)
    # h_batch = torch.zeros(retrain_batch_size)
    # img_id_list = torch.zeros(retrain_batch_size)
    return image_batch, box_batch, w_batch, h_batch, img_id_list


def serverSendWeight(model_path):
    # send updated model parameters to the edge
    msg = modelToMessage(model_path)
    send_weights(s, msg)
    return True


def DetectionRetrain(detector, data_batch, learning_rate=3e-3,
                     lr_decay=1, num_epochs=20, device_type='cpu', **kwargs):
    if device_type == 'gpu':
        detector.to(**to_float_cuda)

    # optimizer setup
    optimizer = optim.SGD(
        filter(lambda p: p.requires_grad, detector.parameters()),
        learning_rate)  # leave betas and eps by default
    lr_scheduler = optim.lr_scheduler.LambdaLR(optimizer,
                                               lambda epoch: lr_decay ** epoch)

    loss_history = []
    detector.train()
    for i in range(num_epochs):
        start_t = time.time()

        images, boxes, w_batch, h_batch, _ = data_batch
        resized_boxes = coord_trans(boxes, w_batch, h_batch, mode='p2a')
        if device == 'gpu':
            images = images.to(**to_float_cuda)
            resized_boxes = resized_boxes.to(**to_float_cuda)

        loss = detector(images, resized_boxes)
        optimizer.zero_grad()
        loss.backward()
        loss_history.append(loss.item())
        optimizer.step()

        end_t = time.time()
        print('(Epoch {} / {}) loss: {:.4f} time per epoch: {:.1f}s'.format(
            i, num_epochs, loss.item(), end_t - start_t))

        lr_scheduler.step()

    return loss_history


# load pretrained model
yoloDetector = SingleStageDetector()
yoloDetector.load_state_dict(torch.load('yolo_detector.pt', map_location=torch.device('cpu')))
print("Model Loaded")
# start listen to the edge, retrain and send back updated model as necessary
while True:
    retrain_data_batch = serverReceiveImg()
    loss_his = DetectionRetrain(yoloDetector, retrain_data_batch, learning_rate=lr,
                                num_epochs=retrain_num_epochs, device_type=device)
    print("Retrain Round " + str(retrain_counter) + " finished with loss " + str(sum(loss_his) / len(loss_his)))
    retrain_counter += 1
    torch.save(yoloDetector.state_dict(), updated_model_path)
    print("Model saved in ", updated_model_path)
    serverSendWeight(updated_model_path)
    print("Model params sent to edge")
