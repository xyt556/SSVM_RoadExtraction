# -*- coding: utf-8 -*-
import os
import numpy as np
import cv2
from u_net import u_net, total_loss
from data_loader import data_loader
from tf_util import *
import tensorflow.contrib.slim as slim

side_loss_sigma = 0.5
def sigmoid_cross_entropy_balanced(logits, label, name='cross_entropy_loss'):
    """
    Implements Equation [2] in https://arxiv.org/pdf/1504.06375.pdf
    Compute edge pixels for each training sample and set as pos_weights to
    tf.nn.weighted_cross_entropy_with_logits
    """
    y = tf.cast(label, tf.float32)

    count_neg = tf.reduce_sum(1. - y)
    count_pos = tf.reduce_sum(y)

    # Equation [2]
    beta = count_neg / (count_neg + count_pos)

    # Equation [2] divide by 1 - beta
    pos_weight = beta / (1 - beta)

    cost = tf.nn.weighted_cross_entropy_with_logits(logits=logits, targets=y, pos_weight=pos_weight)

    # Multiply by 1 - beta
    cost = tf.reduce_mean(cost * (1 - beta))

    # check if image has no edge pixels return 0 else return complete error function
    return tf.where(tf.equal(count_pos, 0.0), 0.0, cost, name=name)

def load_images(fn_list, batch_size):
    images = []
    labels = []
    for i in np.random.randint(len(fn_list), size=(batch_size,)):
        f = np.load(fn_list[i])
        images.append(cv2.resize(f['image'], (480, 480)))
        label = f['label'] / 256
        labels.append(np.reshape(cv2.resize(label, (480, 480)), (480, 480, 1)))
    return np.array(images), np.array(labels)

def get_sess():
    tf_config=tf.ConfigProto()
    tf_config.gpu_options.allow_growth=True
    tf_config.log_device_placement=True
    return tf.Session(config=tf_config)

if __name__ == "__main__":
    import time
    import tensorflow as tf

    DEVICE_STR = "cpu:0"
    BATCH_SIZE = 3
    OUTPUT_DIM = 1

    with tf.device(DEVICE_STR):
        u = u_net(DEVICE_STR, 1e-5, BATCH_SIZE, OUTPUT_DIM)
        output_shape = u.outputs.get_shape().as_list()
        logits = tf.nn.sigmoid(u.outputs, name="pred")
        a = tf.constant(1e-7)

        y_placeholder = tf.placeholder(dtype=tf.float32, shape=output_shape)
        loss = - tf.reduce_mean(y_placeholder * tf.log(logits+a) + (1 - y_placeholder) * tf.log(1 - logits+a))
        for idx, b in enumerate(u.side_outputs):
            output = tf.nn.sigmoid(b, name='output_{}'.format(idx))
            cost = sigmoid_cross_entropy_balanced(b, y_placeholder, name='cross_entropy{}'.format(idx))
            loss += cost * side_loss_sigma
        loss, _, reloss = total_loss("loss", loss)

        l1 = tf.reduce_sum(logits * y_placeholder) / tf.reduce_sum(y_placeholder)  # Recall
        l2 = tf.reduce_sum(logits * y_placeholder) / tf.reduce_sum(logits)  # Precision
        F1 = 2 * l1 * l2 / (l1 + l2)

        opt = tf.train.AdamOptimizer(learning_rate=6e-6)

        update_op = opt.minimize(loss)

    tf.summary.scalar("loss", loss)
    tf.summary.scalar("re loss", reloss)
    tf.summary.scalar("l1", l1)
    tf.summary.scalar("l2", l2)
    tf.summary.scalar("F1", F1)
    tf.summary.image("inputs", u.inputs)
    tf.summary.image("labels", y_placeholder)
    tf.summary.image("outputs", logits)

    merged = tf.summary.merge_all()

    DATA_PATH = "F:\遥感数据\\road\SpaceNet\AOI_2_Vegas_Roads_Train\\train_npz"
    fn_list = [os.path.join(DATA_PATH, fn) for fn in os.listdir(DATA_PATH) if "npz" in fn]
    print("\n".join(fn_list))
    with data_loader(n_workers=4, load_func=load_images) as data:
        i = 0

        saver = tf.train.Saver()
        with get_sess() as sess:
            train_writer = tf.summary.FileWriter('log/road_SVM.T1', sess.graph)
            sess.run(tf.global_variables_initializer())
            #sess.run(load_h5weight("/usr/lhw/young/u_net_classification/models/vgg16_weights_tf.h5", *get_collection()))
            #saver.restore(sess,'models/road.10000-10000')
            for  i in  range(20001):
                images, labels = data(fn_list, BATCH_SIZE)
                feed_dict = {
                    u.inputs: images,
                    y_placeholder: labels
                }
                summary, l, rl, _ = sess.run([merged, loss, reloss, update_op], feed_dict=feed_dict)
                Recall, Precision, F1_re = sess.run([l1, l2, F1], feed_dict=feed_dict)
                if i > 3000 and i % 2000 == 0:
                    saver.save(sess, 'models/road_6m.%d'%i, global_step=i)
                if i % 10 == 0:
                    train_writer.add_summary(summary, i)
                    print("<%d> loss: %.6f, re loss: %.6f"%(i, l, rl))
                    print("<%d> Recall: %.6f, Precision: %.6f, F1: %.6f" % (i, Recall, Precision, F1_re))
                i += 1

