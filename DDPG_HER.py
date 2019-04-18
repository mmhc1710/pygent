import numpy as np
from Agents import Agent
from Data import DataSet
from Algorithms import Algorithm
import torch
import torch.nn as nn
import matplotlib.pyplot as plt
from NeuralNetworkModels import Actor, Critic #ActorBN as Actor, CriticBN as Critic #,
import os
import pickle
import random
import time
from Utilities import  observation

class DDPG_HER(Algorithm):
    """ Deep Deterministic Policy Gradient - Implementation based on PyTorch (https://pytorch.org)
        with Hindsight Expereince Replay
    Attributes:
        n (int): number of episodes
        t (int, float): episode length
        dt (int, float): step size
        meanCost (array): mean cost of an episode
        agent (Agent(object)): agent of the algorithm
        environment (Environment(object)): environment
        eps (float [0, 1]): epsilon-greedy action(control)
        nData: maximum length of data set

    """

    def __init__(self, environment, t, dt, xGoal, plotInterval=50, nData=1e6, path='../Results/DDPG/', checkInterval=100,
                 evalPolicyInterval=100, costScale=100):
        xDim = environment.oDim
        uDim = environment.uDim
        uMax = environment.uMax
        agent = ActorCritic(2*xDim, uDim, torch.Tensor(uMax), dt)
        super(DDPG_HER, self).__init__(environment, agent, t, dt)
        self.R = DataSet(nData)
        self.plotInterval = plotInterval # inter
        self.evalPolicyInterval = evalPolicyInterval
        self.checkInterval = checkInterval  # checkpoint interval
        self.epsDecay = 1.
        self.path = path
        self.costScale = costScale
        self.xGoal = observation(xGoal, self.environment.xIsAngle)
        if not os.path.isdir(path):
            os.makedirs(path)
        if not os.path.isdir(path+'plots/'):
            os.makedirs(path+'plots/')
        if not os.path.isdir(path + 'animations/'):
            os.makedirs(path + 'animations/')
        if not os.path.isdir(path + 'data/'):
            os.makedirs(path + 'data/')

    def goal_cost(self, x, u, g):
        eps = 0.5
        c = 1*(not(all(np.isclose(g, x, atol=eps))))
        return c

    def run_episode(self):
        print('started episode ', self.episode)
        tt = np.arange(0, self.t, self.dt)
        # list of incremental costs
        cost = []
        # reset environment/agent to initial state, delete history
        self.environment.reset(self.environment.x0)
        g = self.xGoal #sample goal (zero-state)
        self.agent.reset()
        for _ in tt:
            # agent computes control/action
            if self.episode % self.evalPolicyInterval == 0:
                u = self.agent.take_action(self.dt, self.environment.o+g)
            else:
                u = self.agent.take_random_action(self.dt, self.environment.o+g)
            # simulation of environment
            c = self.environment.step(self.dt, u)
            c = self.goal_cost(self.environment.o, self.agent.u, g)
            cost.append(c)

            # store transition in dataset (x_, u, x, c)
            transition = ({'x_': self.environment.o_+g, 'u': self.agent.u, 'x': self.environment.o+g, 'c': [c]})
            self.R.add_sample(transition)
            if self.R.data.__len__() > 64 and self.episode > 0:
                self.agent.training(self.R)
            if self.environment.terminated:
                print('Environment terminated!')
                break
        # hindsight experience replay
        g = observation(self.environment.history[-1], self.environment.xIsAngle)
        for x_, u_, x in zip(self.environment.history[:-1], self.agent.history[1:], self.environment.history[1:]):
            # store transition in dataset (x_, u, x, c)
            o_ = observation(x_, self.environment.xIsAngle)
            o = observation(x, self.environment.xIsAngle)
            c = self.goal_cost(o, u, g)
            transition = ({'x_': o_+g, 'u': u_, 'x': o+g, 'c': [c]})
            self.R.add_sample(transition)
        # store the mean of the incremental cost
        self.meanCost.append(np.mean(cost))
        self.totalCost.append(np.sum(cost))
        self.episode += 1

        pass

    def run_controller(self, x0):
        print('started episode ', self.episode)
        tt = np.arange(0, self.t, self.dt)
        # list of incremental costs
        cost = []
        # reset environment/agent to initial state, delete history
        self.environment.reset(x0)
        self.agent.reset()
        for _ in tt:
            # agent computes control/action
            u = self.agent.take_action(self.dt, self.environment.o)

            # simulation of environment
            c = self.environment.step(self.dt, u)
            cost.append(c)

            if self.environment.terminated:
                print('Environment terminated!')
                break
        # store the mean of the incremental cost
        self.meanCost.append(np.mean(cost))
        self.totalCost.append(np.sum(cost))
        pass

    def run_learning(self, n):
        for k in range(1, n+1):
            self.run_episode()
            # plot environment after episode finished
            print('Samples: ',self.R.data.__len__())
            if k % 10 == 0:
                self.learning_curve()
            if k % self.checkInterval == 0:
                self.save()
                # if self.meanCost[-1] < 0.01: # goal reached
            if k % self.plotInterval == 0:
                self.plot()
                self.animation()

    def save(self):
        # save model
        torch.save({'actor': self.agent.actor1.state_dict(),
                 'critic': self.agent.critic1.state_dict()}, self.path+'data/checkpoint.pth')
        self.R.save(self.path+'data/dataSet.p')
        pickle.dump(self.meanCost, open(self.path+'data/meanCost.p', 'wb'))
        pickle.dump(self.totalCost, open(self.path + 'data/totalCost.p', 'wb'))
        pass

    def load(self):
        if os.path.isfile(self.path+'data/checkpoint.pth'):
            checkpoint = torch.load(self.path+'data/checkpoint.pth')
            self.agent.actor1.load_state_dict(checkpoint['actor'])
            self.agent.actor2.load_state_dict(checkpoint['actor'])
            self.agent.critic1.load_state_dict(checkpoint['critic'])
            self.agent.critic2.load_state_dict(checkpoint['critic'])
        else:
            print('Checkpoint file not found!')
        if os.path.isfile(self.path + 'data/dataSet.p'):
            self.R.load(self.path+'data/dataSet.p')
        else:
            print('No dataset found!')
        if os.path.isfile(self.path + 'data/meanCost.p'):
            self.meanCost = pickle.load(open(self.path + 'data/meanCost.p', 'rb'))
            self.episode = self.meanCost.__len__() + 1
        else:
            print('No learning curve data found!')
        if os.path.isfile(self.path + 'data/totalCost.p'):
            self.totalCost = pickle.load(open(self.path + 'data/totalCost.p', 'rb'))
        else:
            print('No learning curve data found!')
        pass


    def plot(self):
        self.environment.plot()
        plt.savefig(self.path+'plots/'+str(self.episode-1)+'_environment.pdf')
        plt.savefig(self.path + 'plots/' + str(self.episode - 1) + '_environment.pgf')
        self.agent.plot()
        plt.savefig(self.path+'plots/'+str(self.episode-1)+'_agent.pdf')
        plt.savefig(self.path + 'plots/' + str(self.episode - 1) + '_agent.pgf')
        plt.close('all')


    def animation(self):
        ani = self.environment.animation()
        if ani != None:
            ani.save(self.path+'animations/'+str(self.episode-1)+'_animation.mp4', fps=1/self.dt)
        plt.close('all')


    def learning_curve(self):
        fig, ax = plt.subplots(2, 1, dpi=150, sharex=True)
        ax[0].step(np.arange(1, self.episode), self.meanCost, 'k', lw=1)
        ax[0].set_ylabel(r'avg. cost/step')
        ax[0].grid(True)
        ax[1].step(np.arange(1, self.episode), self.totalCost, 'k', lw=1)
        ax[1].set_ylabel(r'total cost')
        ax[1].grid(True)
        plt.xlabel(r'Episode')
        plt.savefig(self.path+'learning_curve.pdf')
        plt.savefig(self.path + 'learning_curve.pgf')
        plt.close('all')

class ActorCritic(Agent):
    """ Q-Network (Multi-Layer-Perceptron)
        Q(x,u) -> R

        mu(x) = argmin_u*(Q(x[k],u*)


    Attributes:
        controls (array): control/actions that the agent can choose from
        netStructure (array): array that describes layer structure (i.e. [1, 10, 10, 1])
        eps (float [0, 1]): with probability eps a random action/control is returned
    """

    def __init__(self, xDim, uDim, uMax, dt, gamma=0.98, tau=0.001):
        super(ActorCritic, self).__init__(uDim)
        self.xDim = xDim
        self.uMax = uMax
        self.actor1 = Actor(xDim, uDim, uMax)
        self.actor2 = Actor(xDim, uDim, uMax)
        self.blend_hard(self.actor1, self.actor2)
        self.critic1 = Critic(xDim, uDim)
        self.critic2 = Critic(xDim, uDim)
        self.blend_hard(self.critic1, self.critic2)
        self.gamma = gamma
        self.tau = tau
        self.optimCritic = torch.optim.Adam(self.critic1.parameters(), lr=1e-3, weight_decay=1e-2)
        self.optimActor = torch.optim.Adam(self.actor1.parameters(), lr=1e-4)
        self.noise = OUnoise(uDim, dt)

    def training(self, dataSet):
        # loss function (mean squared error)
        criterion = nn.MSELoss()

        # training data
        x_Inputs, uInputs, qTargets = self.training_data(dataSet)
        # eval mode on (batch normalization)
        for epoch in range(1):  # loop over the dataset multiple times
            qOutputs = self.critic1(x_Inputs, uInputs)
            qOutputs = torch.squeeze(qOutputs)
            muOutputs = self.actor1(x_Inputs)
            self.train()
            # backward + optimize
            lossCritic = criterion(qOutputs, qTargets)
            lossActor = self.critic1(x_Inputs, muOutputs).mean() # -self.critic1(xInputs, muOutputs).mean() when using rewards instead of cost

            #loss.backward(retain_graph=True)
            self.optimCritic.zero_grad()
            lossCritic.backward()
            self.optimCritic.step()

            self.optimActor.zero_grad()
            lossActor.backward()
            self.optimActor.step()

            self.blend(self.critic1, self.critic2)
            self.blend(self.actor1, self.actor2)
            # eval mode on (batch normalization)
            self.eval()
        pass

    def train(self):
        self.actor1.train()
        self.actor2.train()
        self.critic1.train()
        self.critic2.train()

    def eval(self):
        self.actor1.eval()
        self.actor2.eval()
        self.critic1.eval()
        self.critic2.eval()

    def blend(self, source, target):
        for wTarget, wSource in zip(target.parameters(), source.parameters()):
            wTarget.data.copy_(self.tau*wSource.data + (1.0 - self.tau)*wTarget.data)
        return

    def blend_hard(self, source, target):
        for wTarget, wSource in zip(target.parameters(), source.parameters()):
            wTarget.data.copy_(wSource.data)
        return

    def take_action(self, dt, x):
        """ eps-greedy policy """
        # greedy control/action
        self.eval()
        x = torch.Tensor([x])
        self.u = np.asarray(self.actor1(x).detach())[0]
        # self.u = np.clip(np.asarray(self.actor1(x).detach())[0] + self.noise()*self.uMax, -self.uMax, self.uMax)
        self.history = np.concatenate((self.history, np.array([self.u])))  # save current action in history
        self.tt.extend([self.tt[-1] + dt])  # increment simulation time
        self.train()
        return self.u

    def take_random_action(self, dt, x):
        """ random policy """
        #self.u = [np.random.uniform(-self.uMax, self.uMax)]
        self.eval()
        x = torch.Tensor([x])
        u = np.asarray(self.actor1(x).detach())[0] + self.noise.sample()*self.uMax.numpy()
        self.u = np.clip(u, -self.uMax.numpy(), self.uMax.numpy())
        self.history = np.concatenate((self.history, np.array([self.u])))  # save current action in history
        self.tt.extend([self.tt[-1] + dt])  # increment simulation time
        self.train()
        return self.u

    def training_data(self, dataSet):
        # eval mode on (batch normalization)
        batch = dataSet.minibatch(128)
        x_Inputs = torch.Tensor([sample['x_'] for sample in batch])
        xInputs =  torch.Tensor([sample['x'] for sample in batch])
        uInputs =  torch.Tensor([sample['u'] for sample in batch])
        costs =  torch.Tensor([sample['c'] for sample in batch])
        self.eval()
        qTargets = costs + self.gamma*self.critic2(xInputs, self.actor2(xInputs)).detach()
        qTargets = torch.squeeze(qTargets)
        self.train()
        return x_Inputs, uInputs, qTargets


class OUnoise:
    def __init__(self, action_dim, dt, mu=0, theta=0.15, sigma=0.2):
        self.action_dim = action_dim
        self.mu = mu
        self.theta = theta
        self.sigma = sigma
        self.X = np.ones(self.action_dim) * self.mu
        self.dt = dt

    def reset(self):
        self.X = np.ones(self.action_dim) * self.mu

    def sample(self):
        dx = self.theta * (self.mu - self.X)*self.dt + self.sigma * np.random.normal(0, self.dt, len(self.X))
        self.X = self.X + dx

        return self.X