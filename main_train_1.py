import matplotlib.pyplot as plt
import numpy as np
import scipy.stats as stats
import torch

from options import args_parser
from dataset_processing import sampling
from itertools import chain

import Classes.Environment1 as ENV
from ddpg_torch import Agent
from Classes.buffer import ReplayBuffer
from global_critic import Global_Critic

from model import Encoder,Decoder,Discriminator

# 2 RSUs
# ################## SETTINGS ######################
IS_TRAIN = 1
IS_TEST = 1 - IS_TRAIN
label = 'marl_model'

# vehicular network
n_rsu = 1
n_veh = 10
l_s = 1000
cache_size = 50

# 分配车辆数据
# args
args = args_parser()
# gpu or cpu
if args.gpu: torch.cuda.set_device(args.gpu)
device = 'cuda' if args.gpu else 'cpu'

# load sample users_group_train users_group_test
# RSU1
sample1, users_group_train1, users_group_test1, _ = sampling(args, n_veh)
data_set1 = np.array(sample1)
# test_dataset & test_dataset_idx
test_dataset_idxs1 = []
for idx in range(n_veh):
    test_dataset_idxs1.append(users_group_test1[idx])
test_dataset_idxs1 = list(chain.from_iterable(test_dataset_idxs1))
test_dataset1 = data_set1[test_dataset_idxs1]


# vehicle speed 36-54 km/h
mu, sigma = 45, 4.5
lower, upper = mu - 2 * sigma, mu + 2 * sigma  # 截断在[μ-2σ, μ+2σ]
x = stats.truncnorm((lower - mu) / sigma, (upper - mu) / sigma, loc=mu, scale=sigma)
veh_speed = x.rvs(int(n_veh*n_rsu))
for i in range(len(veh_speed)):
    veh_speed[i] = veh_speed[i] * 0.278
print('each vehicle speed:', veh_speed, 'm/s')

# initial position
veh_pos = []
# RSU0 position
s = np.random.randint(0,300,n_veh)
for i in range(int(n_veh*n_rsu)):
    veh_pos.append(s[i])
print('each vehicle initial position:', veh_pos, 'm')

# ------- characteristics related to the DDPG network -------- #
batch_size = 64            # 修改 32->256 ： 2022.7.16
memory_size = 100000
gamma = 0.99
alpha = 0.0001
beta = 0.001
update_actor_interval = 2
noise = 0.3

# actor and critic hidden layers
C_fc1_dims = 1024
C_fc2_dims = 512
C_fc3_dims = 256

A_fc1_dims = 1024
A_fc2_dims = 512
# ------------------------------------------------------------- #

tau = 0.005

env = ENV.Environ(n_veh, veh_speed, cache_size)
env.new_random_game()  # initialize parameters in env

# AAE network (build model)
# init training network classes / architectures
in_si1 = int(max(data_set1[:, 1]))
clo1 = int(max(data_set1[1, :]))

netE1 = Encoder(input_size=in_si1, hidden_size=[256, 64, 16, 4, 2])
netE1.to(device)
netP1 = Decoder(output_size=in_si1, hidden_size=[2, 4, 16, 64, 256])
netP1.to(device)
netD1 = Discriminator(input_size=2, hidden_size=[256, 16, 4, 2], output_size=1)
netD1.to(device)
print('initial RSU1 global model:', netE1, netP1, netD1)

n_step_per_episode = 200

# test episodes
n_episode_test = 100

#  f#
def get_state(env, recommend_movies):
    """ Get state from the environment """
    # get initial action
    cache = env.local_cache(recommend_movies)
    return np.concatenate((np.reshape(cache, -1), np.reshape(recommend_movies, -1)), axis=0)

def get_new_state(action, recommend_movies):
    """ Get state from the environment """
    return np.concatenate((np.reshape(action, -1), np.reshape(recommend_movies, -1)), axis=0)

def actionfunction(action, n):
    action = action.copy()
    a = action.reshape(1,-1)
    idx = np.argpartition(a,-n,axis=1)[:,-n:]
    out = np.zeros(a.shape, dtype=int)
    np.put_along_axis(out,idx,1,axis=1)
    return out

# ------------------------------------------------------------------------------------------------------------------ #
# ------------------------------------------------------------------------------------------------------------------ #
n_input = cache_size * 4
n_output = cache_size * 2  #action
# --------------------------------------------------------------
agents = []
for index_agent in range(n_rsu):
    print("Initializing agent (RSU) ", index_agent)
    agent = Agent(alpha, beta, n_input, tau, n_output, gamma, C_fc1_dims, C_fc2_dims, C_fc3_dims,
                  A_fc1_dims, A_fc2_dims, batch_size, n_rsu, index_agent, noise)
    agents.append(agent)
memory = ReplayBuffer(memory_size, n_input, n_output, n_rsu)
print("Initializing Global critic ...")
global_agent = Global_Critic(beta, n_input, tau, n_output, gamma, C_fc1_dims, C_fc2_dims, C_fc3_dims,
                 batch_size, n_rsu, update_actor_interval, noise)
# ------------------------------------------------------------------------------------------------------------------ #
# ------------------------------------------------------------------------------------------------------------------ #
record_reward_ = np.zeros([n_rsu, args.slots], dtype=np.float64)
record_hit_radio_ = np.zeros([n_rsu, args.slots], dtype=np.float64)
record_critics_loss_ = np.zeros([n_rsu+1, args.slots], dtype=np.float64)
record_actor_loss_ = np.zeros([n_rsu+1, args.slots], dtype=np.float64)
record_critics_value_ = np.zeros([1, args.slots], dtype=np.float64)
record_q1 = np.zeros([1, args.slots], dtype=np.float64)
record_q2 = np.zeros([1, args.slots], dtype=np.float64)
record_cost_ = np.zeros([n_rsu, args.slots], dtype=np.float64)
record_global_reward_ = np.zeros([1, args.slots], dtype=np.float64)
# ------------------------------------------------------------------------------------------------------------------ #
# recommend_movies_cs1, netE1, netP1, netD1 = env.get_content_pop(netE1, netP1, netD1, data_set1, sample1,
#                                                                 users_group_train1, users_group_test1)
# recommend_movies_cs2, netE2, netP2, netD2 = env.get_content_pop(netE2, netP2, netD2, data_set2, sample2,
#                                                                         users_group_train2, users_group_test2)

wwh_test_w_e_all_epochs1 = env.wwh_test_get_lr_para(netE1, netP1, netD1, data_set1, users_group_train1)
# recommend_movies_cs1 = env.wwh_test_get_content_pop(wwh_test_w_e_all_epochs1, data_set1, sample1,
#                                                             users_group_test1)
# recommend_movies_cs2 = env.wwh_test_get_content_pop(wwh_test_w_e_all_epochs2, data_set2, sample2,
#                                                             users_group_test2)

if IS_TRAIN:
    # global_agent.load_models()
    # for i in range(n_platoon):
    #     agents[i].load_models()
    plot_i = 1
    for i_episode in range(args.slots):
        done = False
        print("-------------------------------------------------------------------------------------------------------")
        recommend_movies_cs1, netE1, netP1, netD1 = env.get_content_pop(netE1, netP1, netD1, data_set1, sample1,
                                                                       users_group_train1, users_group_test1)
        # per episode 's each step reward

        # recommend_movies_cs1 = env.wwh_test_get_content_pop(wwh_test_w_e_all_epochs1, data_set1, sample1,
        #                                                     users_group_test1)
        # recommend_movies_cs2 = env.wwh_test_get_content_pop(wwh_test_w_e_all_epochs2, data_set2, sample2,
        #                                                     users_group_test2)

        # index1 = np.random.permutation(recommend_movies_cs1.size)
        # recommend_movies_cs1 = recommend_movies_cs1[index1]
        # index2 = np.random.permutation(recommend_movies_cs2.size)
        # recommend_movies_cs2 = recommend_movies_cs2[index2]

        record_reward = np.zeros([n_rsu, n_step_per_episode], dtype=np.float64)
        record_hit_radio = np.zeros([n_rsu, n_step_per_episode], dtype=np.float64)
        record_cost = np.zeros([n_rsu, n_step_per_episode], dtype=np.float64)
        state_old_all = []

        # rsu 1
        # print('Episode ', i_episode, 'RSU1 elastic federated learning predict contents:', recommend_movies_cs1)

        state1 = get_state(env, recommend_movies_cs1)
        state_old_all.append(state1)

        step_global_reward = []
        for i_step in range(n_step_per_episode):

            state_new_all = []
            action_all = []
            action_new_all = []

            for i in range(n_rsu):
                a = state_old_all[i]
                action = agents[i].choose_action(state_old_all[i])
                action_all.append(action)
                print("RSU : ",i, " action : ", action[:6])
                action_new = action.copy()
                action_new = np.clip(action_new, -0.999, 0.999)
                action_new = actionfunction(action_new, n=cache_size)
                action_new = action_new[0]
                print("RSU : ", i, " action_process : ", action_new[:6])
                action_new_all.append(action_new)

            # All the agents take actions simultaneously, obtain reward, and update the environment
            action_temp = action_new_all.copy()

            #1 RSU 情况下代码
            train_reward, global_reward, train_hit_radio, train_cost = env.act_for_training(action_temp, state_old_all, test_dataset1)
            step_global_reward.append(global_reward)
            for i in range(n_rsu):
                record_reward[i, i_step] = train_reward[i]
                record_hit_radio[i, i_step] = train_hit_radio[i]
                record_cost[i, i_step] = train_cost[i]

            # get new state
            state_new1 = get_new_state(action_temp[0], recommend_movies_cs1)
            state_new_all.append(state_new1)

            if i_step == n_step_per_episode - 1:
                done = True

            # taking the agents actions, states and reward
            if done == False:
                memory.store_transition(np.asarray(state_old_all).flatten(), np.asarray(action_all).flatten(),
                                        global_reward/1e1, train_reward/1e1, np.asarray(state_new_all).flatten(), done)

            # agents take random samples and learn
            if memory.mem_cntr >= batch_size:              # 修改 ： 2022.7.16
                states, actions, rewards_g, rewards_l, states_, dones = memory.sample_buffer(batch_size)
                global_agent.global_learn(agents, states, actions, rewards_g, rewards_l, states_, dones)

            # old observation = new_observation
            for i in range(n_rsu):
                state_old_all[i] = state_new_all[i]
            print("-----------------------------------")
            print('Episode:', i_episode)
            print('iteration:', i_step)
            #print('cache actions :\n', action_new_all)
            #print('agents rewards :\n', train_reward)
            #print('agents global rewards :\n', global_reward)

        # plt.plot(step_global_reward)
        # plt.show()

        record_reward_[:, i_episode] = np.mean(record_reward, axis=1)
        record_hit_radio_[:, i_episode] = np.mean(record_hit_radio, axis=1)
        record_cost_[:, i_episode] = np.mean(record_cost, axis=1)
        record_global_reward_[0, i_episode] = np.mean(np.asarray(step_global_reward))
        # ---------------------------------------------------------------------------------------

        # if plot_i % 10 == 0:
        #     x_g = [i for i in range(200)]
        #     plt.plot(x_g,global_agent.Global_Loss)
        #     plt.show()
        #     x_l = [i for i in range(100)]
        #     plt.plot(x_l,agents[0].local_critic_loss)
        #     plt.show()
        #     plt.plot(x_l, agents[1].local_critic_loss)
        #     plt.show()

        # -----------------------------------------------------------------------------------------
        record_critics_loss_[0, i_episode] = np.mean(np.asarray(global_agent.Global_Loss))
        global_agent.Global_Loss = []
        for i in range(n_rsu):
            record_critics_loss_[i+1, i_episode] = np.mean(np.asarray(agents[i].local_critic_loss))
            agents[i].local_critic_loss = []
            record_actor_loss_[i+1,i_episode] = np.mean(np.asarray(agents[i].local_actor_loss))
            agents[i].local_actor_loss = []

        record_critics_value_[0, i_episode] = np.mean(np.asarray(global_agent.critic_value))
        global_agent.critic_value = []
        # record_q1[0, i_episode] = np.mean(np.asarray(global_agent.q1))
        # global_agent.q1 = []
        # record_q2[0, i_episode] = np.mean(np.asarray(global_agent.q2))
        # global_agent.q2 = []
        if plot_i % 100 == 0:
            x = [i for i in range(len(record_critics_loss_[0][:i_episode]))]
            # plt.plot(record_critics_loss_[0][:i_episode])
            # plt.title("critic loss")
            # plt.show()

            plt.plot(x,record_critics_loss_[0][:i_episode])
            plt.legend(["critic loss"])
            plt.show()

            plt.plot(x,record_critics_value_[0][:i_episode])
            plt.legend(["critic value"])
            plt.show()
            # plt.plot(record_global_reward_[0][:i_episode])
            # plt.title("global reward")
            # plt.show()
            plt.plot(x,record_global_reward_[0][:i_episode],
                     x,record_reward_[0][:i_episode])
            plt.legend(["global reward","RSU1 reward"])
            plt.show()


            # plt.plot(record_reward_[1][:i_episode])
            # plt.title("actor2 reward")
            # plt.show()
            # plt.plot(record_actor_loss_[1,:i_episode])
            # plt.title("actor1 actor loss")
            # plt.show()
            # plt.plot(record_actor_loss_[2,:i_episode])
            # plt.title("actor2 actor loss")
            # plt.show()

        plot_i += 1
        if i_episode == args.slots - 1:
            global_agent.save_models()
            for i in range(n_rsu):
                agents[i].save_models()

        veh_pos = env.renew_positions(veh_pos)
        #print('Episode ', i_episode, "'s each vehicle position: ", veh_pos)

    #print('reward:',record_reward_)
    #print('critic_loss',record_critics_loss_)
    #print('critic_value', record_critics_value_)
    #print('cache hit radio', record_hit_radio_)
    #print('cache cost', record_cost_)
    # current_dir = os.path.dirname(os.path.realpath(__file__))
    #
    # reward_path = os.path.join(current_dir, "model/" + label + '/reward.mat')
    # critic_loss_path = os.path.join(current_dir, "model/" + label + '/critic_loss.mat')
    #
    # scipy.io.savemat(reward_path, {'reward': record_reward_})
    # scipy.io.savemat(critic_loss_path, {'critic_loss': record_critics_loss_})
    record_critics_loss_ = np.array(record_critics_loss_)
    np.save('D:\PyCharm\project\project\project_pysyft\Maddpg_ealstic_fl\data\\1\\loss1_50.npy',record_critics_loss_)

    record_critics_value_ = np.array(record_critics_value_)
    np.save('D:\PyCharm\project\project\project_pysyft\Maddpg_ealstic_fl\data\\1\\value1_50.npy',record_critics_value_)

    netE1.save_checkpoint()
    netP1.save_checkpoint()
    netD1.save_checkpoint()
    print("over")
    # global_agent.save_models()
    # for i in range(n_rsu):
    #     agents[i].save_models()