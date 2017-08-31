# -*- coding: utf-8 -*-

from os import path
from math import sqrt
import numpy as np
from mpi4py import MPI
from scipy.special import expit

from config import hp


class SingleNNP(object):
    def __init__(self, comm, rank, nsample, ninput):
        self.comm = comm
        self.rank = rank
        self.natom = hp.natom
        self.nsample = nsample
        self.input_nodes = ninput
        self.hidden1_nodes = hp.hidden_nodes
        self.hidden2_nodes = hp.hidden_nodes
        self.output_nodes = 1
        self.learning_rate = hp.learning_rate
        self.beta = hp.beta
        self.gamma = hp.gamma

        # initialize weight parameters
        self.w, self.b = [], []
        self.w.append(np.random.normal(0.0, 0.5, (self.hidden1_nodes, self.input_nodes)))
        self.b.append(np.random.normal(0.0, 0.5, (self.hidden1_nodes)))
        self.w.append(np.random.normal(0.0, 0.5, (self.hidden2_nodes, self.hidden1_nodes)))
        self.b.append(np.random.normal(0.0, 0.5, (self.hidden2_nodes)))
        self.w.append(np.random.normal(-0.1, 0.5, (self.output_nodes, self.hidden2_nodes)))
        self.b.append(np.random.normal(-0.1, 0.5, (self.output_nodes)))

        # accumulation of weight parameters and bias parameters
        self.v_w = [np.zeros_like(self.w[0]), np.zeros_like(self.w[1]), np.zeros_like(self.w[2])]
        self.v_b = [np.zeros_like(self.b[0]), np.zeros_like(self.b[1]), np.zeros_like(self.b[2])]

        # define activation function and derivative
        self.activation_func = lambda x: expit(x)
        self.dif_activation_func = lambda x: expit(x) * (1 - expit(x))

    def train(self, nsubset, subdataset):
        w_grad_sum = [np.zeros_like(self.w[0]), np.zeros_like(self.w[1]), np.zeros_like(self.w[2])]
        b_grad_sum = [np.zeros_like(self.b[0]), np.zeros_like(self.b[1]), np.zeros_like(self.b[2])]

        # before calculating grad_sum, renew weight and bias parameters with old v_w and v_b
        for i in range(3):
            self.w[i] += self.gamma * self.v_w[i]
            self.b[i] += self.gamma * self.v_b[i]

        # calculate grad_sum
        for n in range(nsubset):
            Et = subdataset[n][0]
            Frt = subdataset[n][1]
            G = subdataset[n][2]
            dG = subdataset[n][3]
            E = self.__query_E(G[self.rank])
            Fr = self.__query_F(G[self.rank], dG[self.rank])
            E_error = Et - E
            F_errors = Frt - Fr
            w_grad, b_grad = self.__gradient(G[self.rank], dG[self.rank], E_error, F_errors)
            for i in range(3):
                w_recv = np.zeros_like(w_grad[i])
                b_recv = np.zeros_like(b_grad[i])
                self.comm.Allreduce(w_grad[i], w_recv, op=MPI.SUM)
                self.comm.Allreduce(b_grad[i], b_recv, op=MPI.SUM)
                w_grad_sum[i] += w_recv
                b_grad_sum[i] += b_recv

        # renew weight and bias parameters with calculated gradient
        for i in range(3):
            self.w[i] += w_grad_sum[i] / (nsubset * self.natom)
            self.b[i] += b_grad_sum[i] / (nsubset * self.natom)
            self.v_w[i] = (self.gamma * self.v_w[i]) + (w_grad_sum[i] / (nsubset * self.natom))
            self.v_b[i] = (self.gamma * self.v_b[i]) + (b_grad_sum[i] / (nsubset * self.natom))

    def save_w(self, dire, name):
        np.save(path.join(dire, name+'_wih1.npy'), self.w[0])
        np.save(path.join(dire, name+'_wh1h2.npy'), self.w[1])
        np.save(path.join(dire, name+'_wh2o.npy'), self.w[2])
        np.save(path.join(dire, name+'_bih1.npy'), self.b[0])
        np.save(path.join(dire, name+'_bh1h2.npy'), self.b[1])
        np.save(path.join(dire, name+'_bh2o.npy'), self.b[2])

    def load_w(self, dire, name):
        self.w[0] = np.load(path.join(dire, name+'_wih1.npy'))
        self.w[1] = np.load(path.join(dire, name+'_wh1h2.npy'))
        self.w[2] = np.load(path.join(dire, name+'_wh2o.npy'))
        self.b[0] = np.load(path.join(dire, name+'_bih1.npy'))
        self.b[1] = np.load(path.join(dire, name+'_bh1h2.npy'))
        self.b[2] = np.load(path.join(dire, name+'_bh2o.npy'))

    def calc_RMSE(self, dataset):
        E_MSE = 0.0
        F_MSE = 0.0
        for n in range(self.nsample):
            Et = dataset[n][0]
            Frt = dataset[n][1]
            G = dataset[n][2]
            dG = dataset[n][3]
            E_out = self.__query_E(G[self.rank])
            F_rout = self.__query_F(G[self.rank], dG[self.rank])
            E_MSE += (Et - E_out) ** 2
            F_MSE += np.sum((Frt - F_rout)**2)
        E_RMSE = sqrt(E_MSE / self.nsample)
        F_RMSE = sqrt(F_MSE / (self.nsample * self.natom * 3))
        RMSE = E_RMSE + self.beta * F_RMSE
        return E_RMSE, F_RMSE, RMSE

    def __gradient(self, Gi, dGi, E_error, F_errors):
        # feed_forward
        self.__energy(Gi)

        # back_prop
        # energy
        e_output_errors = np.array([E_error])
        e_hidden2_errors = self.dif_activation_func(self.hidden2_inputs) * np.dot(self.w[2].T, e_output_errors)
        e_hidden1_errors = self.dif_activation_func(self.hidden1_inputs) * np.dot(self.w[1].T, e_hidden2_errors)

        e_grad_output_cost = np.dot(e_output_errors[:, None], self.hidden2_outputs[None, :])
        e_grad_hidden2_cost = np.dot(e_hidden2_errors[:, None], self.hidden1_outputs[None, :])
        e_grad_hidden1_cost = np.dot(e_hidden1_errors[:, None], Gi[None, :])

        # forces
        f_output_errors = np.zeros(1)
        f_hidden2_errors = np.zeros(self.hidden2_nodes)
        f_hidden1_errors = np.zeros(self.hidden1_nodes)
        f_grad_output_cost = np.zeros((self.output_nodes, self.hidden2_nodes))
        f_grad_hidden2_cost = np.zeros((self.hidden2_nodes, self.hidden1_nodes))
        f_grad_hidden1_cost = np.zeros((self.hidden1_nodes, self.input_nodes))
        for r in range(3*self.natom):
            f_output_error = np.array([F_errors[r]])
            coef = np.dot(self.w[1], self.dif_activation_func(self.hidden1_inputs) * np.dot(self.w[0], dGi[r]))
            f_hidden2_error = self.dif_activation_func(self.hidden2_inputs) * \
                np.dot(- self.w[2], (1 - 2 * self.hidden2_outputs) * coef) * f_output_error
            f_hidden1_error = self.dif_activation_func(self.hidden1_inputs) * \
                np.dot(self.w[1].T, f_hidden2_error)

            f_output_errors += f_output_error
            f_hidden2_errors += f_hidden2_error
            f_hidden1_errors += f_hidden1_error
            f_grad_output_cost += np.dot(f_output_error[:, None], (- self.dif_activation_func(self.hidden2_inputs) * coef)[None, :])
            f_grad_hidden2_cost += np.dot(f_hidden2_error[:, None], self.hidden1_outputs[None, :])
            f_grad_hidden1_cost += np.dot(f_hidden1_error[:, None], Gi[None, :])

    # modify weight parameters
        w_grad, b_grad = [], []
        w_grad.append(self.learning_rate * (e_grad_hidden1_cost - self.beta * f_grad_hidden1_cost / (3*self.natom)))
        w_grad.append(self.learning_rate * (e_grad_hidden2_cost - self.beta * f_grad_hidden2_cost / (3*self.natom)))
        w_grad.append(self.learning_rate * (e_grad_output_cost - self.beta * f_grad_output_cost / (3*self.natom)))
        b_grad.append(self.learning_rate * (e_hidden1_errors - self.beta * f_hidden1_errors / (3*self.natom)))
        b_grad.append(self.learning_rate * (e_hidden2_errors - self.beta * f_hidden2_errors / (3*self.natom)))
        b_grad.append(self.learning_rate * (e_output_errors - self.beta * f_output_errors / (3*self.natom)))
        return w_grad, b_grad

    def __energy(self, Gi):
        # feed_forward
        self.hidden1_inputs = np.dot(self.w[0], Gi) + self.b[0]
        self.hidden1_outputs = self.activation_func(self.hidden1_inputs)
        self.hidden2_inputs = np.dot(self.w[1], self.hidden1_outputs) + self.b[1]
        self.hidden2_outputs = self.activation_func(self.hidden2_inputs)
        self.final_inputs = np.dot(self.w[2], self.hidden2_outputs) + self.b[2]
        final_outputs = self.final_inputs
        return final_outputs

    def __force(self, Gi, dGi):
        #self.__energy(Gi) 他で一度計算してるのでいらない？
        hidden1_outputs = np.dot(self.w[0], dGi)
        hidden2_inputs = self.dif_activation_func(self.hidden1_inputs) * hidden1_outputs
        hidden2_outputs = np.dot(self.w[1], hidden2_inputs)
        final_inputs = self.dif_activation_func(self.hidden2_inputs) * hidden2_outputs
        final_outputs = -1 * np.dot(self.w[2], final_inputs)
        return final_outputs.reshape(-1) # convert shape(1,1) to shape(1)

    def __query_E(self, Gi):
        Ei = self.__energy(Gi)
        E = np.zeros(1)
        self.comm.Allreduce(Ei, E, op=MPI.SUM)
        return E[0]

    def __query_F(self, Gi, dGi):
        Fir = np.zeros(3*self.natom)
        for r in range(3*self.natom):
            Fir[r] = self.__force(Gi, dGi[r])
        Fr = np.zeros(3*self.natom)
        self.comm.Allreduce(Fir, Fr, op=MPI.SUM)
        return Fr
