#!/usr/bin/python
# -*- coding: utf-8 -*-
import os
import sys
sys.path.append('Codes')
import tensorflow as tf
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pickle
from dataShaping import *
from savePerf import *
from saveTransformedGraph import optimizeGraph
import scipy.io.wavfile
import time
from tensorflow.contrib.layers import fully_connected
from tensorflow.contrib.rnn import *




modelName = "LSTM29"
# create directory experiment
date = time.strftime("%Y-%m-%d-%H-%M")
path = os.path.join("Experiments",date)
if not os.path.isdir(path):
    os.makedirs(path)
    #experiment/"date"/temp will contain the backuped model parameters
    pathTemp = os.path.join(path,'temp')
    os.makedirs(pathTemp)
    # if you run the file two time in a minute
else :
    date = date+'(2)'
    path = os.path.join("Experiments",date)
    os.makedirs(path)
    pathTemp = os.path.join(path,'temp')
    os.makedirs(pathTemp)

# directory that will contain tensorboard information
pathLog = 'Tf_logs'
if not os.path.isdir(pathLog):
    os.makedirs(pathLog)
pathLog = "{}/run-{}/".format(pathLog,date)

version = tf.__version__
print ("version {} of tensorflow".format(version))

#############################
# Model parameters
#############################
trainTestRatio = 0.8
#if you cannot load all the data set in Ram specify wich part you want to load (0 means all the dataset)
maxSize = 0
num_step = 150                                       # time step before reduction
#num_LSTM = 10                                         # num LSTM (time step after reduction)
conv_chan = 35                                         #number of kernel for convolution
conv_strides = 3#int(np.ceil(num_step/num_LSTM))                  #decay between two convolution
conv_size = 12                                         #filter size for the convolution
size_poll = 4
reg_scale = 0
l1l2Prop = 0.4  # 1 =>l1, 0=> l2
reg_scale_l1 = l1l2Prop*reg_scale
reg_scale_l2 = ((1-l1l2Prop)/2)*reg_scale
num_hidden = 200                                      #num of hidden units
num_class = 1                                          #size of the output
num_feature = 1                                        # size of the input
batch_size = 2500                                   # number of sequence taken before to compute the gradient
n_layer = 1                                             #num_layer

#num_hidden = num_hidden/keep_prob
num_epoch = 100000                                      # process all the datas num_epoch times
trainDuration = 60*60*15                             # or during a determined duration(second)
fileNameTrain = 'Datasets/trainingMesaMarkVClean.mat'             #dataset train/test path
fileNameTest = 'Datasets/testMesaMarkVClean.mat' # dataset validation path
fileNameValidation = 'Datasets/valMesaMarkVClean.mat'

#############################
# Loading data
#############################
matrix = sio.loadmat(fileNameTrain)
matrixTrain = matrix['train']
matrix = sio.loadmat(fileNameTest)
matrixTest = matrix['test']
if maxSize ==0:
    maxSize = len(matrixTrain)
    print("maxSize = {}".format(maxSize))
# to do shuffle matrix by num_step length

train_input,train_output,test_input,test_output = loadInputOutput(matrixTrain,matrixTest,num_step,maxSize)
print("shape input train {}".format(np.shape(train_input)))
numTrain = len(train_output)
print ("Data loaded")
#######################
#Graph
#######################

G = tf.Graph()
with G.as_default():
    with tf.name_scope("placeHolder"):
        data = tf.placeholder(tf.float32, [None, num_step], name ="data") #Number of examples, number of input step (time step), dimension of each input
        target = tf.placeholder(tf.float32, [None, num_class],name = "target") # batchSize, nbClass

    dataShaped = tf.reshape(data,[tf.shape(data)[0],num_step,1,1]) # batchSize, num_step num_feature
    with tf.variable_scope("ConvLayers"):
        regularizerC1 = tf.contrib.layers.l1_l2_regularizer(scale_l1=reg_scale_l1,scale_l2=reg_scale_l2,scope="regC1")
        dataReduced = tf.layers.conv2d(inputs = dataShaped,filters = conv_chan,
                                       kernel_size = (conv_size,1),strides=(4,1),
                                       padding = "same",activation=tf.nn.elu,kernel_regularizer=regularizerC1,name="C1")#batch_size num_Lstm num_channel
        regularizerC2 = tf.contrib.layers.l1_l2_regularizer(scale_l1=reg_scale_l1,scale_l2=reg_scale_l2,scope="regC2")
        dataReduced = tf.layers.conv2d(inputs = dataReduced,filters = conv_chan,
                                       kernel_size = (conv_size,1),strides=(3,1),
                                       padding = "same",activation=tf.nn.elu,kernel_regularizer=regularizerC2,name="C2")#batch_size num_Lstm num_channel
        #regularizerC3 = tf.contrib.layers.l1_l2_regularizer(scale_l1=reg_scale_l1,scale_l2=reg_scale_l2,scope="regC3")
        #dataReduced = tf.layers.conv2d(inputs = dataReduced,filters = conv_chan,
        #                               kernel_size = (conv_size,1),strides=(2,1),
        #                               padding = "same",activation=tf.nn.elu,kernel_regularizer=regularizerC3,name="C3")#batch_size num_Lstm num_channel
    dataReduced = tf.reshape(dataReduced,[tf.shape(data)[0],tf.shape(dataReduced)[1],conv_chan])
    
    fusedCell = tf.contrib.rnn.LSTMBlockFusedCell(num_hidden,use_peephole=False)
    # tf.contrib.rnn.LSTMBlockCell(num_hidden,use_peephole=True)
    #tf.contrib.rnn.LSTMCell(num_hidden,state_is_tuple=True,activation = tf.nn.tanh) 
    #[batch_size, self._num_units]
    #
    dataReduced = tf.transpose(dataReduced,[1,0,2])

    with tf.name_scope("extractLastValueLSTM"):
        val, state = fusedCell(dataReduced,initial_state=None,dtype=tf.float32) # val dim is [batchSize,num_step, numhidden]
    # Let's first fetch the last index of seq length
    # last_index would have a scalar value
        last_index = tf.shape(val)[0] - 1
    # Then let's reshape the output to [sequence_length,batch_size,numhidden]
    # for convenience
        #val = tf.transpose(val,[1,0,2])
    # Last state of all batches
        #last = tf.nn.embedding_lookup(val,last_index) # tensor [batchsize,numhidden]
        last = tf.gather(val,last_index)

    #Send the output of the lsat LSTM cell into a Fully connected layer to compute the prediciton pred[n] 
    
    with tf.variable_scope("FCLayer"):
        regularizerFC1 = tf.contrib.layers.l1_l2_regularizer(scale_l1=reg_scale_l1,scale_l2=reg_scale_l2,scope="regFC1")
        weight = tf.get_variable("weight", shape=[num_hidden, int(target.get_shape()[1])],regularizer=regularizerFC1, initializer=tf.contrib.layers.xavier_initializer())
        bias = tf.get_variable("bias",shape=[target.get_shape()[1]], dtype=tf.float32,initializer=tf.zeros_initializer)
        prediction = tf.nn.tanh((tf.add(tf.matmul(last, weight) , bias)),name = "prediction") #[batchSize,nclass]
    
    #prediction = fully_connected(last,int(target.get_shape()[1]),activation_fn=tf.nn.elu,weights_regularizer=None,scope="FCPred")
    #Compute the mean square error
    MSE = tf.reduce_mean(tf.square(prediction-target))
    
    #get regularizer
    reg_losses = tf.get_collection(tf.GraphKeys.REGULARIZATION_LOSSES)
    MSEReg = tf.add_n([MSE]+reg_losses,name="MSEReg")
    # create optimizer
    optimizer = tf.train.AdamOptimizer()
    #Compute gradient and apply backpropagation
    minimize = optimizer.minimize(MSEReg)

    # Create summary view for tensorboard
    mse_summary = tf.summary.scalar('RMSE',tf.sqrt(MSE))
    #kernels = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES,'ConvLayers/C1/kernel')[0]
    #kernels1 = tf.reshape(tf.slice(kernels,[0,0,0,0],[12,1,1,1]),[-1])
    #kernels2 = tf.reshape(kernels,[1,12,30,1])
    #imag_summary=tf.summary.image('kernels',kernels2,max_outputs=1)
    #histogram_summary = tf.summary.histogram('kernelC1',kernels1)
    summary_op = tf.summary.merge_all()
    
    #Create an init op to initialize variable
    init_op = tf.global_variables_initializer()
    saver = tf.train.Saver() # save variable, use saver.restore(sess,"date/tmp/my_model.ckpt") instead of sess.run(init_op)

##############################
# Execution du graphe
##############################
    
with tf.Session(graph=G) as sess:
    #restorePath = os.path.join('2017-09-11-18-07','temp','my_model.ckpt') # example for restore a previous model
    #saver.restore(sess,restorePath)
    sess.run(init_op)
    train_writer = tf.summary.FileWriter(pathLog+'train',graph =tf.get_default_graph())
    test_writer = tf.summary.FileWriter(pathLog+'test')

    no_of_batches = int(np.floor((numTrain)/batch_size)) # numtrain -numstep ?
    no_of_batchesTest = int(np.floor((len(test_input))/batch_size))
    tStart = time.clock()
    epoch =0
    for epoch in range(num_epoch):
        tEpoch = time.clock()
        if (time.clock()-tStart < trainDuration):
            ptr = 0
            if epoch % 20==0 : # each ten epoch save the model
                tf.train.write_graph(sess.graph_def,"{}/".format(pathTemp),'myGraph.pb',as_text=False)
                save_path = saver.save(sess,os.path.join(pathTemp,'myModel.ckpt'))
            pMSETrain=0
            for j in range(no_of_batches):
                inp, out = train_input[ptr:ptr+batch_size],train_output[ptr:ptr+batch_size]
                ptr+=batch_size
                if j % np.floor(numTrain/len(test_input)) ==0 : # This is to have a train summary and a test summary of the same size
                    _,summary_str,pMSETrainTemp,pLast = sess.run([minimize,summary_op,MSE,last],{data: inp, target: out})
                    #print("shape:{}".format(numTrain/len(test_input)))
                    #print("Kernels1:{}".format(pKernels1))
                    #print("Kernels2:{}".format(pKernels2))
                    pMSETrain += pMSETrainTemp
                    step = epoch*no_of_batches+j
                    train_writer.add_summary(summary_str,step)
                else :
                    sess.run([minimize],{data: inp, target: out})
                   
            RMSETrain = np.sqrt(pMSETrain/no_of_batchesTest)
            print ("Epoch -{} calculated in {:5.2f} s ".format(epoch,time.clock()-tEpoch))
            # evaluate the model on the test set (compute the mean of the MSE)
            pMSE = 0
            ptr2 = 0
            for k in range(no_of_batchesTest):
                pMSETemp,summary_str = sess.run([MSE,summary_op],{data: test_input[ptr2:ptr2+batch_size] , target: test_output[ptr2:ptr2+batch_size]})
                pMSE += pMSETemp
                ptr2 += batch_size
                step = epoch*no_of_batchesTest+k
                test_writer.add_summary(summary_str,step*np.floor(numTrain/len(test_input)))
                RMSETest=np.sqrt(pMSE/no_of_batchesTest)
            print("Epoch {} MSE {:.5} on test set with deviation of {:.2f}%".format(epoch,RMSETest,100*np.sqrt((RMSETrain-RMSETest)**2)/RMSETrain))
        else : break # break the while loop if number of epoch is reached
    tStop = time.clock()
    trainTime = time.strftime("%d:%H:%M:%S ", time.gmtime(tStop-tStart))
    
    #######################
    # Save Graph variable and information about the running session
    #######################
    # save graph model
    tf.train.write_graph(sess.graph_def,"{}/".format(pathTemp),'myFinalGraph.pbtxt',as_text=True)
    # Save checkpoint variables
    save_path = saver.save(sess,os.path.join(pathTemp,'myFinalModel.ckpt'))
    print ("Training duration {}".format(trainTime))
    totalParameters =np.sum([np.product([xi.value for xi in x.get_shape()]) for x in tf.trainable_variables()])
    print("Number of training variable {}".format(totalParameters))
    # log
    infoLog={}
    infoLog["path"] = path
    infoLog["MSE"] = np.sqrt(pMSE/no_of_batchesTest)
    infoLog["num_step"] = num_step
    infoLog["num_hidden"] = num_hidden
    infoLog["num_epoch"] = epoch
    infoLog["batch_size"] = batch_size
    infoLog["maxSize"] = maxSize
    infoLog["duration"] = trainTime
    infoLog["totalParameters"] = totalParameters
    infoLog["version"] = version
    infoLog["n_layer"] = n_layer
    infoLog["trainDropout"] = 0
    infoLog["nameModel"] = modelName
    infoLog["conv_chan"] = conv_chan
    infoLog["strides"] = conv_strides
    infoLog["conv_size"] = conv_size
    logPerf(infoLog)
    input_nodes=["placeHolder/data"]
    output_nodes=["FCLayer/prediction"]
    optimizeGraph(pathTemp,input_nodes,output_nodes)
    
    
                                                 
    
    ###############################
    #   validation dataset and emulate guitar signal
    ###############################
    matrixVal = sio.loadmat(fileNameValidation)
    matrixVal = matrixVal['val']  
    # shape validation test
    val_input,val_output = shapeData(matrixVal,num_step,maxSize)
    lPrediction = []
    lTarget = []
    ptr3 = 0
    no_of_batchesVal = int(np.floor((len(val_input))/batch_size))
    for k in range(no_of_batchesVal):
        pPrediction,pTarget = sess.run([prediction,target],{data: val_input[ptr3:ptr3+batch_size], target: val_output[ptr3:ptr3+batch_size]}) 
        lPrediction.append(pPrediction)
        lTarget.append(pTarget)   
        ptr3+=batch_size
    #plt.show()scree
    predictionArray = np.array(lPrediction,dtype=np.float32).ravel()
    targetArray = np.array(lTarget,dtype=np.float32).ravel()
    scipy.io.wavfile.write(os.path.join(path,'prediction.wav'),44100,predictionArray)
    scipy.io.wavfile.write(os.path.join(path,'target.wav'),44100,targetArray)

    # save emulation in a pickle format
    ax = plt.subplot(111)
    ax.plot(predictionArray[:10000],label='prediction')
    ax.plot(targetArray[:10000],label='target')
    ax.legend()
    nameFigEstimation = os.path.join(path,"targetVsPrediction.pickle")
    pickle.dump(ax,open(nameFigEstimation, 'wb'))
print ("done, good job kids")

