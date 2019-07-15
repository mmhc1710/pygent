import numpy as np
np.random.seed(0)
import torch
torch.manual_seed(0)
import torch.nn as nn
import matplotlib.pyplot as plt
import os
import pickle
import inspect
from shutil import copyfile
import copy

# pygent
from pygent.agents import Agent
from pygent.data import DataSet
from pygent.environments import StateSpaceModel
from pygent.algorithms.core import Algorithm
from pygent.algorithms.nmpc import NMPC
from pygent.nn_models import NNDynamics

class MBRL(Algorithm):

    def __init__(self, environment, t, dt, plotInterval=5, nData=1e6, path='../results/mbrl/', checkInterval=50,
                 evalPolicyInterval=100, warm_up=10000, dyn_lr=1e-3, batch_size=512, aggregation_interval=10,
                 fcost=None, horizon=None, use_mpc_plan=True):
        xDim = environment.xDim
        uDim = environment.uDim
        uMax = environment.uMax
        if horizon == None:
            if use_mpc_plan == True:
                horizon = t
            else:
                horizon = 100*dt
        self.nn_dynamics = NNDynamics(xDim, uDim) # neural network dynamics
        self.optim = torch.optim.Adam(self.nn_dynamics.parameters(), lr=dyn_lr)
        nn_environment = StateSpaceModel(self.ode, environment.cost, environment.x0, uDim, dt)
        nn_environment.uMax = uMax
        #agent = MPCAgent(uDim, nn_environment, horizon, dt, path)
        self.nmpc_algorithm = NMPC(copy.deepcopy(nn_environment), copy.deepcopy(nn_environment), t, dt, horizon,
                                   path=path, fcost=fcost, fastForward=False, init_optim=False)
        super(MBRL, self).__init__(environment, self.nmpc_algorithm.agent, t, dt)
        self.R = DataSet(nData)
        self.R_RL = DataSet(nData)
        self.plotInterval = plotInterval  # inter
        self.evalPolicyInterval = evalPolicyInterval
        self.checkInterval = checkInterval  # checkpoint interval
        self.path = path
        self.warm_up = warm_up
        self.batch_size = batch_size
        self.dyn_steps_train = 500
        self.aggregation_interval = aggregation_interval
        self.use_mpc_plan=use_mpc_plan
        self.dynamics_first_trained = False

        if not os.path.isdir(path):
            os.makedirs(path)
        if not os.path.isdir(path + 'plots/'):
            os.makedirs(path + 'plots/')
        if not os.path.isdir(path + 'animations/'):
            os.makedirs(path + 'animations/')
        if not os.path.isdir(path + 'data/'):
            os.makedirs(path + 'data/')
        copyfile(inspect.stack()[-1][1], path + 'exec_script.py')
        self.expCost = []
        self.episode_steps = []

    def ode(self, t, x, u):
        if type(u)==type(list()):
            u = np.array([u])
        if type(x)==type(list()):
            x = np.array([x])
        if u.ndim == 1:
            u = u.reshape(1, len(u))
        if x.ndim == 1:
            x = x.reshape(1, len(x))
        rhs = self.nn_dynamics(torch.Tensor(x), torch.Tensor(u)).detach().numpy()
        return rhs[0]

    def run_episode(self):
        """ Run a training episode. If terminal state is reached, episode stops."""

        print('Started episode ', self.episode)
        print(self.R.data.__len__())
        tt = np.arange(0, self.t, self.dt)
        cost = []  # list of incremental costs
        disc_cost = [] # discounted cost

        # reset environment/agent to initial state, delete history
        self.environment.reset(self.environment.x0)
        self.agent.reset()
        use_mpc = False
        if self.R.data.__len__() >= self.warm_up and self.dynamics_first_trained:#self.batch_size:
            use_mpc = True
            self.agent.traj_optimizer.environment.reset(self.environment.x)
            self.agent.init_optim()

        for i, t in enumerate(tt):
            # agent computes control/action
            if use_mpc:
                noise = np.random.normal(loc=0.0, scale=0.005, size=self.environment.uDim)
                if self.use_mpc_plan:
                    u = self.agent.take_action_plan(self.dt, self.environment.x, i) + noise
                else:
                    u = self.agent.take_action(self.dt, self.environment.x) + noise
            else:
                u = self.agent.take_random_action(self.dt)
            # simulation of environment
            c = self.environment.step(u, self.dt)
            cost.append(c)
            disc_cost.append(c)

            # store transition in data set (x_, u, x, c)
            transition = ({'x_': self.environment.x_, 'u': self.agent.u, 'x': self.environment.x,
                           'c': [c], 't': [self.environment.terminated]})

            # add sample to data set
            if self.R.data.__len__() < self.warm_up:
                self.R.force_add_sample(transition)
            else:
                self.R_RL.force_add_sample(transition)

            # check if environment terminated
            if self.environment.terminated:
                print('Environment terminated!')
                break

        # store the mean of the incremental cost
        self.meanCost.append(np.mean(cost))
        self.totalCost.append(np.sum(disc_cost))
        self.episode_steps.append(i)
        self.episode += 1
        pass

    def run_controller(self, x0):
        """ Run an episode, where the policy network is evaluated. """

        print('Started episode ', self.episode)
        tt = np.arange(0, self.t, self.dt)
        cost = []  # list of incremental costs

        # reset environment/agent to initial state, delete history
        self.environment.reset(x0)
        self.agent.reset()

        for i, t in enumerate(tt):
            # agent computes control/action
            u = self.agent.take_action(self.dt, self.environment.x) + self.uMax*np.random.normal(0, 0.005, self.uDim)

            # simulation of environment
            c = self.environment.step(u, self.dt)
            cost.append(c)

            # check if environment terminated
            if self.environment.terminated:
                print('Environment terminated!')
                break
        pass

    def run_learning(self, n):
        """ Learning process.

            Args:
                n (int): number of episodes
        """

        for k in range(1, int(n) + 1):
            if self.R.data.__len__()>=self.warm_up:#self.batch_size:
                for i in range(5000):
                    self.train_dynamics()
            for i in range(10):
                self.run_episode()
                if (self.episode - 1) % self.plotInterval == 0:
                    self.plot()
                    self.animation()
            # plot environment after episode finished
            print('Samples: ', self.R.data.__len__(), self.R_RL.data.__len__())
            if self.episode % 10 == 0:
                self.learning_curve()
            if self.episode % self.checkInterval == 0:
                self.save()
                # if self.meanCost[-1] < 0.01: # goal reached
        pass

    def save(self):
        """ Save neural network parameters and data set. """

        # save network parameters
        torch.save({'nn_dynamics': self.nn_dynamics.state_dict()}, self.path + 'data/checkpoint.pth')

        # save data set
        self.R.save(self.path + 'data/dataSet.p')

        # save learning curve data
        learning_curve_dict = {'totalCost': self.totalCost, 'meanCost':self.meanCost,
                               'expCost': self.expCost, 'episode_steps': self.episode_steps}

        pickle.dump(learning_curve_dict, open(self.path + 'data/learning_curve.p', 'wb'))
        print('Network parameters, data set and learning curve saved.')
        pass

    def load(self):
        """ Load neural network parameters and data set. """

        # load network parameters
        if os.path.isfile(self.path + 'data/checkpoint.pth'):
            checkpoint = torch.load(self.path + 'data/checkpoint.pth')
            self.nn_dynamics.load_state_dict(checkpoint['nn_dynamics'])
            print('Loaded neural network parameters!')
        else:
            print('Could not load neural network parameters!')

        # load data set
        if os.path.isfile(self.path + 'data/dataSet.p'):
            self.R.load(self.path + 'data/dataSet.p')
            print('Loaded data set!')
        else:
            print('No data set found!')

        # load learning curve
        if os.path.isfile(self.path + 'data/learning_curve.p'):
            learning_curve_dict = pickle.load(open(self.path + 'data/learning_curve.p', 'rb'))
            self.meanCost = learning_curve_dict['meanCost']
            self.totalCost = learning_curve_dict['totalCost']
            self.expCost = learning_curve_dict['expCost']
            self.episode_steps = learning_curve_dict['episode_steps']
            self.episode = self.meanCost.__len__() + 1
            print('Loaded learning curve data!')
        else:
            print('No learning curve data found!')
        self.run_controller(self.environment.x0)
        pass

    def plot(self):
        """ Plots the environment's and agent's history. """

        self.environment.plot()
        plt.savefig(self.path + 'plots/' + str(self.episode - 1) + '_environment.pdf')
        self.agent.plot()
        plt.savefig(self.path + 'plots/' + str(self.episode - 1) + '_agent.pdf')
        plt.close('all')
        pass

    def animation(self):
        """ Animation of the environment (if available). """

        ani = self.environment.animation()
        if ani != None:
            try:
                ani.save(self.path + 'animations/' + str(self.episode - 1) + '_animation.mp4', fps=1 / self.dt)
            except:
                ani.save(self.path + 'animations/' + str(self.episode - 1) + '_animation.gif', fps=1 / self.dt)
        plt.close('all')
        pass

    def learning_curve(self):
        """ Plot of the learning curve. """

        fig, ax = plt.subplots(2, 1, dpi=150, sharex=True, figsize=(5.56, 3.44))

        #x = np.arange(1, self.episode)
        x = np.linspace(1, self.R.data.__len__(), self.episode-1)
        x = np.cumsum(self.episode_steps)

        ax[0].step(x, self.meanCost, 'b', lw=1, label=r'$\frac{1}{N}\sum_{k=0}^N c_k$')
        ax[0].legend(loc='center', bbox_to_anchor=(1.15, .5), ncol=1, shadow=True)
        ax[0].grid(True)
        ax[0].ticklabel_format(axis='both', style='sci', scilimits=(-3,4), useMathText=True)
        ax[1].step(x, self.totalCost, 'b', lw=1, label=r'$\sum_{k=0}^N\gamma^k c_k$')
        ax[1].grid(True)
        ax[1].legend(loc='center', bbox_to_anchor=(1.15, .5), ncol=1, shadow=True)
        ax[1].ticklabel_format(axis='both', style='sci',scilimits=(-3,5), useMathText=True)
        plt.rc('font', family='serif')
        plt.xlabel('Samples')
        plt.tight_layout()
        plt.savefig(self.path + 'learning_curve.pdf')
        try:
            plt.savefig(self.path + 'learning_curve.pgf')
        except:
            pass
        # todo: save learning curve data
        plt.close('all')
        pass

    def train_dynamics(self):
        self.dynamics_first_trained = True

        for iter in range(self.dyn_steps_train):
            loss = self.train_dynamics_data(self.R)
            for i in range(9):
                loss = self.train_dynamics_data(self.R_RL)

    def train_dynamics_data(self, dataSet):
        # loss function (mean squared error)
        criterion = nn.MSELoss()
        # create training data/targets
        #batch = dataSet.minibatch(self.batch_size)
        running_loss = 0.0
        batch = dataSet.random_batch(self.batch_size)
        for iter in range(1):
            x_Inputs, xInputs, fOutputs = self.training_data(batch)
            # definition of loss functions
            loss = criterion(fOutputs, (xInputs - x_Inputs)/self.dt)
            # train
            self.optim.zero_grad()  # delete gradients
            loss.backward()  # error back-propagation
            self.optim.step()  # gradient descent step
            running_loss += loss.item()
            #self.eval() # eval mode on (batch normalization)
        return running_loss / max(1, iter)

    def training_data(self, batch):
        x_Inputs = torch.Tensor([sample['x_'] for sample in batch])
        xInputs = torch.Tensor([sample['x'] for sample in batch])
        uInputs = torch.Tensor([sample['u'] for sample in batch])
        fOutputs = self.nn_dynamics(x_Inputs, uInputs)
        return x_Inputs, xInputs, fOutputs


