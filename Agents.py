import numpy as np
from abc import abstractmethod, abstractproperty
# import scipy.integrate as sci
from scipy.integrate import solve_ivp
import matplotlib.pyplot as plt
import random

class Agent(object):
    """ Base class for an agent. """

    def __init__(self, m):
        self.tt = [0]
        self.history = np.zeros([1, m])
        self.m = m

    @abstractmethod
    def take_action(self, *args):
        return

    def reset(self):
        self.tt = [0]
        self.history = np.zeros([1, self.m])

class FeedBack(Agent):
    """Agent subclass: a standard state feedback of the form u = mu(x)

        Attributes:
            mu (function): feedback law
            tt (array):
            history (array): previous states (x[0],x[1],...,x[k-1])
            tt (list): time vector (corresponding to history)

        """

    def __init__(self, mu, m):
        super(FeedBack, self).__init__(m)
        self.mu = mu

    def take_action(self, dt, x):
        """ Computes control/action of the agent

        Args:
            dt (int, float): duration of step (not solver step size)
            x (array): state

        Returns:
            u (array): control/action

        """

        self.u = self.mu(x)  # compute control signal
        self.history = np.concatenate((self.history, np.array([self.u])))  # save current action in history
        self.tt.extend([self.tt[-1] + dt])  # increment simulation time

        return self.u

    def plot(self):
        """ Plots the agents history (the control trajectory)

        Returns:
            fig (matplotlib.pyplot.figure)

        """

        fig, ax = plt.subplots(len(self.u), 1, sharex='col')
        # Plot control trajectories
        fig.suptitle('Controls')
        for i in range(len(self.u)):
            ax[i].step(self.tt, self.history[:, i], label=r'$u_'+str(i+1)+'$')
            ax[i].grid(True)
            ax[i].legend(loc='upper right')
        plt.xlabel('t in s')

        return fig, ax

