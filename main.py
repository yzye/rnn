# -*- coding: utf-8 -*-
"""
Created on Mon Apr  2 22:06:23 2018

@author: yuzhe
"""

import numpy as np
import tensorflow as tf
import jieba
import re
import itertools
from random import shuffle
import argparse
from collections import Counter

def input_doc(filename):
    '''
    eliminate na or 没有描述
    '''
    
    reviews = []
    r = "[\s+\.\!\/_,$%^*)(+\"\']+|[+——！，。？、~@#￥%……&*（）]+"
    with open(filename, 'r', encoding = "utf-8") as f:
        for lines in f:        
            if re.sub(r,'',lines) not in ["na","没有描述"]:
                reviews.append([re.sub(r,'',x) for x in jieba.cut(lines) if len(re.sub(r,'',x))])
    return reviews

def get_labels(reviews_pos,reviews_neg):
    
    labels = np.array([1]*len(reviews_pos)+[0]*len(reviews_neg))
    labels = labels.reshape([-1,1])
    labels = np.hstack((labels,1 - labels))
    
    return labels

def reviews_encode(reviews,min_count):
    
    words = list(itertools.chain.from_iterable(reviews))
    counts = Counter(words)
    
    counts = {k:v for k, v in counts.items() if v>= min_count}
    
    vocab = sorted(counts, key=counts.get, reverse=True)
    vocab_to_int = {word: ii for ii, word in enumerate(vocab, 1)}
    vocab_to_int['<UNK>'] = len(vocab_to_int)+1
    
    words = [w if w in vocab_to_int else '<UNK>' for w in words]
    
    reviews_ints = []
    for each in reviews:
        reviews_ints.append([vocab_to_int[word] if word in vocab_to_int else vocab_to_int['<UNK>'] for word in each])
        
    return reviews_ints, vocab_to_int

def clean_reviews(reviews_ints,labels):
    '''
    eliminate vacant reviews and shuffle the data
    '''
    non_zero_idx = [ii for ii, review in enumerate(reviews_ints) if len(review) != 0]
    shuffle(non_zero_idx)
    reviews_ints = [reviews_ints[ii] for ii in non_zero_idx]
    labels = np.array([labels[ii] for ii in non_zero_idx])
    
    return reviews_ints,labels

def get_testdata(input_int,labels):
    
    idx = [ii for ii, review in enumerate(input_int) if len(review) != 0]
    output_ints = [input_int[ii] for ii in idx]
    output_labels = [labels[ii] for ii in idx]
    
    return output_ints, output_labels

def padding(reviews_ints,seq_len):
    
    features = np.zeros((len(reviews_ints), seq_len), dtype=int)
    for i, row in enumerate(reviews_ints):
        features[i, -len(row):] = np.array(row)[:seq_len]
    
    return features

def split_features(features,labels,split_frac):
    
    split_idx = int(len(features)*split_frac)

    train_x, val_x = features[:split_idx], features[split_idx:]
    train_y, val_y = labels[:split_idx], labels[split_idx:]

    return train_x, val_x, train_y, val_y

def single_cell(num_hidden, keep_prob):
    cell = tf.contrib.rnn.GRUCell(num_hidden)
    cell = tf.contrib.rnn.DropoutWrapper(cell, output_keep_prob=keep_prob)
    return cell

def my_attention(inputs, hidden_layer_size):
  
    X = tf.reshape(inputs, [-1, 2*num_hidden])
    Y = tf.layers.dense(X, hidden_layer_size, activation=tf.nn.relu)
    logits = tf.layers.dense(Y, 1, activation = None)
  
    logits = tf.reshape(logits, [-1, seq_len, 1])
    alphas = tf.nn.softmax(logits, axis=1)
    encoded_sentence = tf.reduce_sum(inputs * alphas, axis=1)

    return encoded_sentence, alphas

def get_batches(x, y, batch_size=100):
    
    n_batches = len(x)//batch_size
    x, y = x[:n_batches*batch_size], y[:n_batches*batch_size]
    for ii in range(0, len(x), batch_size):
        yield x[ii:ii+batch_size], y[ii:ii+batch_size]

def key_words(inputs, alphas):
    
    alphas = alphas.flatten()
    alphas.shape = (len(inputs),seq_len)

    index = [(seq_len-sum(n>0))+np.argmax(a[seq_len-sum(n>0):]) for a,n in zip(alphas,inputs)]
    int_words = [sen[i] for i,sen in zip(index,inputs)]

    key_words = [[key for key, value in vocab_to_int.items() if value == int_word][0] for int_word in int_words]
    
    return key_words
        
if __name__ == '__main__':
    
    argparser = argparse.ArgumentParser()
    argparser.add_argument("--pos_data", help="Positive data for training",
                           type=str, default=None, required=False)
    argparser.add_argument("--neg_data", help="Negative data for training",
                           type=str, default=None, required=False)
    argparser.add_argument("--epochs", help="epochs for training, default=0",
                           type=str, default=1, required=False)
    
    args = argparser.parse_args()

    reviews_pos = input_doc(args.pos_data)
    reviews_neg = input_doc(args.neg_data)

    reviews = reviews_pos + reviews_neg
    labels = get_labels(reviews_pos,reviews_neg)

    min_count=50
    reviews_ints,vocab_to_int = reviews_encode(reviews,min_count)

    # Generate test_data
    test_ints, test_y = get_testdata(reviews_ints,labels)

    reviews_ints,labels = clean_reviews(reviews_ints,labels)
    
    seq_len = 80
    features = padding(reviews_ints,seq_len)
    test_x = padding(test_ints,seq_len)

    split_frac = 0.8
    train_x, val_x, train_y, val_y = split_features(features,labels,split_frac)
    
    n_words = len(vocab_to_int) + 1 # Adding 1 because we use 0's for padding, dictionary started at 1

    train_graph = tf.Graph()

    with train_graph.as_default():
        # Training Parameters
        learning_rate = 0.001
        epochs = int(args.epochs)
        batch_size = 64
        display_step = 200

        # Network Parameters
        embed_size = 300
        num_hidden = 50 # hidden layer num of features
        num_classes = 2
        att_hidden = 32
    
        # tf Graph input
        inputs_ = tf.placeholder(tf.int32, [None, seq_len], name="input")
        labels_ = tf.placeholder(tf.int32, [None, num_classes], name="labels")
        keep_prob = tf.placeholder(tf.float32, name='keep_prob')

        embedding = tf.Variable(tf.random_uniform([n_words, embed_size]))
        embed = tf.nn.embedding_lookup(embedding, inputs_)

        rnn_fw_cell = single_cell(num_hidden, keep_prob)
        rnn_bw_cell = single_cell(num_hidden, keep_prob)

        outputs, _ = tf.nn.bidirectional_dynamic_rnn(rnn_fw_cell, rnn_bw_cell, embed, dtype=tf.float32)
        outputs = tf.concat(outputs, axis = 2)

        encoded, alphas = my_attention(outputs, att_hidden)

        logits = tf.layers.dense(encoded, 2, activation=None)
        prediction = tf.nn.softmax(logits)

    with train_graph.as_default():

        # Define loss and optimizer
        loss_op = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits_v2(
                logits=logits, labels=labels_))
        optimizer = tf.train.AdamOptimizer(learning_rate)
        train_op = optimizer.minimize(loss_op)
        
        # Evaluate model (with test logits, for dropout to be disabled)
        correct_pred = tf.equal(tf.argmax(prediction, 1), tf.argmax(labels_, 1))
        accuracy = tf.reduce_mean(tf.cast(correct_pred, tf.float32))

        # Initialize the variables (i.e. assign their default value)
        init = tf.global_variables_initializer()

        saver = tf.train.Saver() 

    with tf.Session(graph=train_graph) as sess:
        # Run the initializer
        sess.run(init)
        step = 0
        for epoch in range(epochs):
            for batch_x, batch_y in get_batches(train_x, train_y, batch_size):
                step += 1
                # Run optimization op (backprop)
                sess.run(train_op, feed_dict={inputs_: batch_x, labels_: batch_y, keep_prob: 0.8})
                if step % display_step == 0 or step == 1:
                    loss, acc = sess.run([loss_op, accuracy], feed_dict={inputs_: batch_x,
                                                                        labels_: batch_y,
                                                                        keep_prob: 0.8})
                    print("Step " + str(step) + ", Minibatch Loss= " + \
                          "{:.4f}".format(loss) + ", Training Accuracy= " + \
                          "{:.3f}".format(acc), ", Testing Accuracy=", \
                          sess.run(accuracy, feed_dict={inputs_: val_x[:5000,:], labels_: val_y[:5000,:], keep_prob:1}))
                    
        prediction_step=0
        for batch_x, batch_y in get_batches(test_x, test_y, batch_size):
            pred, a = sess.run([prediction, alphas], feed_dict={inputs_: batch_x,
                                                                        labels_: batch_y,
                                                                        keep_prob: 1})
            key = key_words(batch_x,a)
            prediction_step += 1
            if prediction_step % display_step ==0 :print("Prediction_Step:" + str(prediction_step))
            with open("output.txt","a") as output:
                for p,k in zip(pred,key):
                    label_pred = ("positive","negative")[np.argmax(p)]
                    output.write('\n'+label_pred+'\t'+k)
                                
        print("Prediction Finished!")
        saver.save(sess, "checkpoints/sentiment.ckpt")    

