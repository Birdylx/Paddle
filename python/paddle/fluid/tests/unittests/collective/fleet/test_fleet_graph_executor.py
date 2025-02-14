# Copyright (c) 2020 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import unittest

from launch_function_helper import launch_func

import paddle
import paddle.distributed.fleet as fleet
import paddle.distributed.fleet.base.role_maker as role_maker


class TestFleetGraphExecutionMetaOptimizer(unittest.TestCase):
    def test_graph_execution_optimizer(self):
        node_a = {
            "PADDLE_TRAINER_ID": "0",
            "PADDLE_CURRENT_ENDPOINT": "127.0.0.1:36001",
            "PADDLE_TRAINERS_NUM": "2",
            "PADDLE_TRAINER_ENDPOINTS": "127.0.0.1:36001,127.0.0.1:36002",
            "http_proxy": "",
            "https_proxy": "",
        }

        node_b = {
            "PADDLE_TRAINER_ID": "1",
            "PADDLE_CURRENT_ENDPOINT": "127.0.0.1:36002",
            "PADDLE_TRAINERS_NUM": "2",
            "PADDLE_TRAINER_ENDPOINTS": "127.0.0.1:36001,127.0.0.1:36002",
            "http_proxy": "",
            "https_proxy": "",
        }

        def node_func():
            role = role_maker.PaddleCloudRoleMaker(is_collective=True)
            fleet.init(role)
            input_x = paddle.fluid.layers.data(
                name="x", shape=[32], dtype='float32'
            )
            input_y = paddle.fluid.layers.data(
                name="y", shape=[1], dtype='int64'
            )

            fc_1 = paddle.static.nn.fc(x=input_x, size=64, activation='tanh')
            fc_2 = paddle.static.nn.fc(x=fc_1, size=64, activation='tanh')
            prediction = paddle.static.nn.fc(
                x=[fc_2], size=2, activation='softmax'
            )
            cost = paddle.nn.functional.cross_entropy(
                input=prediction,
                label=input_y,
                reduction='none',
                use_softmax=False,
            )
            avg_cost = paddle.mean(x=cost)

            strategy = paddle.distributed.fleet.DistributedStrategy()
            strategy.nccl_comm_num = 2
            strategy.sync_nccl_allreduce = True
            optimizer = paddle.optimizer.SGD(learning_rate=0.01)
            optimizer = fleet.distributed_optimizer(
                optimizer, strategy=strategy
            )
            optimizer.minimize(avg_cost)
            exe = paddle.fluid.Executor(place=paddle.fluid.CPUPlace())
            exe.run(paddle.fluid.default_startup_program())

            import numpy as np

            def gen_data():
                return {
                    "x": np.random.random(size=(128, 32)).astype('float32'),
                    "y": np.random.randint(2, size=(128, 1)).astype('int64'),
                }

            for i in range(5):
                cost_val = exe.run(feed=gen_data(), fetch_list=[avg_cost.name])
                print("cost of step[{}] = {}".format(i, cost_val))

        # rank 1
        proc_b = launch_func(node_func, node_b)
        proc_b.start()

        # rank 0, for wait server ready coverage
        # just for coverage
        for key in node_a:
            os.environ[key] = node_a[key]
        node_func()

        proc_b.join()


if __name__ == "__main__":
    unittest.main()
