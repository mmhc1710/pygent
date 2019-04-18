from Environments import CartPoleDoubleParallel
from iLQR import iLQR
import numpy as np
import matplotlib.pyplot as plt
def cost(x_, u_, x):
    x1, x2, x3, x4, x5, x6 = x_
    u1, = u_
    c = 0.5*(0.1*x1**2 + 1.*x2**2 + 1.*x3**2 + 0.01*x4**2 + 0.01*x5**2 + 0.01*x6**2 + .01*u1**2)
    return c

def finalcost(x):
    x1, x2, x3, x4, x5, x6 = x
    c = 0.5*(1.*x1**2 + 10.*x2**2 + 10.*x3**2 + 1.*x4**2 + 1.*x5**2 + 1.*x6**2)
    return c

x0 = [0, np.pi, np.pi, 0, 0, 0]

cartPole = CartPoleDoubleParallel(cost, x0)
t = 6
dt = 0.01

path = '../Results/iLQR/CartPoleDoubeParallel/'
controller = iLQR(cartPole, t, dt, constrained=True, fcost=finalcost, path=path)
controller.run_optim()

controller.plot()
plt.show()
controller.animation()