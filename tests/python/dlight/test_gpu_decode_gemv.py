# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
# pylint: disable=missing-docstring,line-too-long,invalid-name,too-few-public-methods,too-many-locals
from tvm import dlight as dl
from tvm.ir import assert_structural_equal
from tvm.script import ir as I
from tvm.script import tir as T
from tvm.target import Target


def test_decode_gemv_1():
    # NK layout + K as decode dim
    # fmt: off
    @I.ir_module
    class Before:
        @T.prim_func
        def func(W: T.Buffer((4096, 512), "uint32"), S: T.Buffer((4096, 128), "float16"), V: T.Buffer((1, 1, 4096), "float16"), C: T.Buffer((1, 1, 4096), "float16")):
            T.func_attr({"global_symbol": "main", "tir.noalias": T.bool(True)})
            B = T.alloc_buffer((4096, 4096), "float16")
            for i, j in T.grid(4096, 4096):
                with T.block("decode"):
                    v_i, v_j = T.axis.remap("SS", [i, j])
                    T.reads(W[v_i, v_j // 8], S[v_i, v_j // 32])
                    T.writes(B[v_i, v_j])
                    B[v_i, v_j] = (T.Cast("float16", T.bitwise_and(T.shift_right(W[v_i, v_j // 8], T.Cast("uint32", v_j % 8) * T.uint32(4)), T.uint32(15))) - T.float16(7)) * S[v_i, v_j // 32]
            for i0, i1, i2, k in T.grid(1, 1, 4096, 4096):
                with T.block("matmul"):
                    v_i0, v_i1, v_i2, v_k = T.axis.remap("SSSR", [i0, i1, i2, k])
                    T.reads(V[v_i0, v_i1, v_k], B[v_i2, v_k])
                    T.writes(C[v_i0, v_i1, v_i2])
                    with T.init():
                        C[v_i0, v_i1, v_i2] = T.float16(0)
                    C[v_i0, v_i1, v_i2] = C[v_i0, v_i1, v_i2] + V[v_i0, v_i1, v_k] * B[v_i2, v_k]


    @I.ir_module
    class After:
        @T.prim_func
        def func(W: T.Buffer((4096, 512), "uint32"), S: T.Buffer((4096, 128), "float16"), V: T.Buffer((1, 1, 4096), "float16"), C: T.Buffer((1, 1, 4096), "float16")):
            T.func_attr({"global_symbol": "main", "tir.is_scheduled": 1, "tir.noalias": T.bool(True)})
            # with T.block("root"):
            C_rf_local = T.alloc_buffer((256, 1, 1, 4096), "float16", scope="local")
            for i2_i0_i1_fused in T.thread_binding(4096, thread="blockIdx.x"):
                for k_0_fused_1 in T.thread_binding(256, thread="threadIdx.x"):
                    with T.block("matmul_rf_init"):
                        vk_0_fused_1 = T.axis.spatial(256, k_0_fused_1)
                        v_i2 = T.axis.spatial(4096, i2_i0_i1_fused)
                        C_rf_local[vk_0_fused_1, 0, 0, v_i2] = T.float16(0)
                    for k_0_fused_0, k_1 in T.grid(2, 8):
                        with T.block("matmul_rf_update"):
                            vk_0_fused_1 = T.axis.spatial(256, k_0_fused_1)
                            v_i2, vk_0_fused_0, vk_1 = T.axis.remap("SRR", [i2_i0_i1_fused, k_0_fused_0, k_1])
                            C_rf_local[vk_0_fused_1, 0, 0, v_i2] = C_rf_local[vk_0_fused_1, 0, 0, v_i2] + V[0, 0, (vk_0_fused_0 * 256 + vk_0_fused_1) * 8 + vk_1] * ((T.Cast("float16", T.bitwise_and(T.shift_right(W[v_i2, vk_0_fused_0 * 256 + vk_0_fused_1], T.Cast("uint32", ((vk_0_fused_0 * 256 + vk_0_fused_1) * 8 + vk_1) % 8) * T.uint32(4)), T.uint32(15))) - T.float16(7)) * S[v_i2, (vk_0_fused_0 * 256 + vk_0_fused_1) // 4])
                for ax1_ax2_ax3_fused in range(1): # pylint: disable=unused-variable
                    for ax0_fused in T.thread_binding(256, thread="threadIdx.x"):
                        with T.block("matmul"):
                            vk_0_fused_1 = T.axis.reduce(256, ax0_fused)
                            v_i2 = T.axis.spatial(4096, i2_i0_i1_fused)
                            with T.init():
                                C[0, 0, v_i2] = T.float16(0)
                            C[0, 0, v_i2] = C[0, 0, v_i2] + C_rf_local[vk_0_fused_1, 0, 0, v_i2]
    # fmt: on

    target = Target("nvidia/geforce-rtx-3090-ti")
    with target:
        mod = dl.ApplyDefaultSchedule(dl.gpu.DecodeGEMV())(Before)  # pylint: disable=not-callable
    assert_structural_equal(mod, After)


def test_decode_gemv_2():
    # KN layout + K as decode dim
    # fmt: off
    @I.ir_module
    class Before:
        @T.prim_func
        def func(W: T.Buffer((512, 4096), "uint32"), S: T.Buffer((128, 4096), "float16"), V: T.Buffer((1, 1, 4096), "float16"), C: T.Buffer((1, 1, 4096), "float16")):
            T.func_attr({"global_symbol": "main", "tir.noalias": T.bool(True)})
            # with T.block("root"):
            B = T.alloc_buffer((4096, 4096), "float16")
            for i, j in T.grid(4096, 4096):
                with T.block("decode"):
                    v_i, v_j = T.axis.remap("SS", [i, j])
                    T.reads(W[v_i // 8, v_j], S[v_i // 32, v_j])
                    T.writes(B[v_i, v_j])
                    B[v_i, v_j] = (T.Cast("float16", T.bitwise_and(T.shift_right(W[v_i // 8, v_j], T.Cast("uint32", v_i % 8) * T.uint32(4)), T.uint32(15))) - T.float16(7)) * S[v_i // 32, v_j]
            for i0, i1, i2, k in T.grid(1, 1, 4096, 4096):
                with T.block("matmul"):
                    v_i0, v_i1, v_i2, v_k = T.axis.remap("SSSR", [i0, i1, i2, k])
                    T.reads(V[v_i0, v_i1, v_k], B[v_k, v_i2])
                    T.writes(C[v_i0, v_i1, v_i2])
                    with T.init():
                        C[v_i0, v_i1, v_i2] = T.float16(0)
                    C[v_i0, v_i1, v_i2] = C[v_i0, v_i1, v_i2] + V[v_i0, v_i1, v_k] * B[v_k, v_i2]


    @I.ir_module
    class After:
        @T.prim_func
        def func(W: T.Buffer((512, 4096), "uint32"), S: T.Buffer((128, 4096), "float16"), V: T.Buffer((1, 1, 4096), "float16"), C: T.Buffer((1, 1, 4096), "float16")):
            T.func_attr({"global_symbol": "main", "tir.is_scheduled": 1, "tir.noalias": T.bool(True)})
            # with T.block("root"):
            C_rf_local = T.alloc_buffer((16, 1, 1, 4096), "float16", scope="local")
            for i2_i0_i1_fused_0 in T.thread_binding(256, thread="blockIdx.x"):
                for i2_i0_i1_fused_1 in T.thread_binding(16, thread="threadIdx.x"):
                    for k_0_fused_1 in T.thread_binding(16, thread="threadIdx.y"):
                        with T.block("matmul_rf_init"):
                            vk_0_fused_1 = T.axis.spatial(16, k_0_fused_1)
                            v_i2 = T.axis.spatial(4096, i2_i0_i1_fused_0 * 16 + i2_i0_i1_fused_1)
                            C_rf_local[vk_0_fused_1, 0, 0, v_i2] = T.float16(0)
                        for k_0_fused_0, k_1 in T.grid(32, 8):
                            with T.block("matmul_rf_update"):
                                vk_0_fused_1 = T.axis.spatial(16, k_0_fused_1)
                                v_i2 = T.axis.spatial(4096, i2_i0_i1_fused_0 * 16 + i2_i0_i1_fused_1)
                                vk_0_fused_0, vk_1 = T.axis.remap("RR", [k_0_fused_0, k_1])
                                C_rf_local[vk_0_fused_1, 0, 0, v_i2] = C_rf_local[vk_0_fused_1, 0, 0, v_i2] + V[0, 0, (vk_0_fused_0 * 16 + vk_0_fused_1) * 8 + vk_1] * ((T.Cast("float16", T.bitwise_and(T.shift_right(W[vk_0_fused_0 * 16 + vk_0_fused_1, v_i2], T.Cast("uint32", ((vk_0_fused_0 * 16 + vk_0_fused_1) * 8 + vk_1) % 8) * T.uint32(4)), T.uint32(15))) - T.float16(7)) * S[(vk_0_fused_0 * 16 + vk_0_fused_1) // 4, v_i2])
                for ax1_ax2_ax3_fused in T.thread_binding(16, thread="threadIdx.x"):
                    for ax0_fused in T.thread_binding(16, thread="threadIdx.y"):
                        with T.block("matmul"):
                            vk_0_fused_1 = T.axis.reduce(16, ax0_fused)
                            v_i2 = T.axis.spatial(4096, i2_i0_i1_fused_0 * 16 + ax1_ax2_ax3_fused)
                            with T.init():
                                C[0, 0, v_i2] = T.float16(0)
                            C[0, 0, v_i2] = C[0, 0, v_i2] + C_rf_local[vk_0_fused_1, 0, 0, v_i2]

    # fmt: on

    target = Target("nvidia/geforce-rtx-3090-ti")
    with target:
        mod = dl.ApplyDefaultSchedule(dl.gpu.DecodeGEMV())(Before)  # pylint: disable=not-callable
    assert_structural_equal(mod, After)


def test_decode_gemv_3():
    # NK layout + N as decode dim
    # fmt: off
    @I.ir_module
    class Before:
        @T.prim_func
        def func(W: T.Buffer((512, 4096), "uint32"), S: T.Buffer((128, 4096), "float16"), V: T.Buffer((1, 1, 4096), "float16"), C: T.Buffer((1, 1, 4096), "float16")):
            T.func_attr({"global_symbol": "main", "tir.noalias": T.bool(True)})
            # with T.block("root"):
            B = T.alloc_buffer((4096, 4096), "float16")
            for i, j in T.grid(4096, 4096):
                with T.block("decode"):
                    v_i, v_j = T.axis.remap("SS", [i, j])
                    T.reads(W[v_i // 8, v_j], S[v_i // 32, v_j])
                    T.writes(B[v_i, v_j])
                    B[v_i, v_j] = (T.Cast("float16", T.bitwise_and(T.shift_right(W[v_i // 8, v_j], T.Cast("uint32", v_i % 8) * T.uint32(4)), T.uint32(15))) - T.float16(7)) * S[v_i // 32, v_j]
            for i0, i1, i2, k in T.grid(1, 1, 4096, 4096):
                with T.block("matmul"):
                    v_i0, v_i1, v_i2, v_k = T.axis.remap("SSSR", [i0, i1, i2, k])
                    T.reads(V[v_i0, v_i1, v_k], B[v_i2, v_k])
                    T.writes(C[v_i0, v_i1, v_i2])
                    with T.init():
                        C[v_i0, v_i1, v_i2] = T.float16(0)
                    C[v_i0, v_i1, v_i2] = C[v_i0, v_i1, v_i2] + V[v_i0, v_i1, v_k] * B[v_i2, v_k]


    @I.ir_module
    class After:
        @T.prim_func
        def func(W: T.Buffer((512, 4096), "uint32"), S: T.Buffer((128, 4096), "float16"), V: T.Buffer((1, 1, 4096), "float16"), C: T.Buffer((1, 1, 4096), "float16")):
            T.func_attr({"global_symbol": "main", "tir.is_scheduled": 1, "tir.noalias": T.bool(True)})
            # with T.block("root"):
            C_rf_local = T.alloc_buffer((256, 1, 1, 4096), "float16", scope="local")
            for i2_0_i0_i1_fused in T.thread_binding(512, thread="blockIdx.x"):
                for k_fused_1 in T.thread_binding(256, thread="threadIdx.x"):
                    for i2_1_init in range(8):
                        with T.block("matmul_rf_init"):
                            vk_fused_1 = T.axis.spatial(256, k_fused_1)
                            v_i1 = T.axis.spatial(512, i2_0_i0_i1_fused)
                            v_i2 = T.axis.spatial(8, i2_1_init)
                            C_rf_local[vk_fused_1, 0, 0, v_i1 * 8 + v_i2] = T.float16(0)
                    for k_fused_0, i2_1 in T.grid(16, 8):
                        with T.block("matmul_rf_update"):
                            vk_fused_1 = T.axis.spatial(256, k_fused_1)
                            v_i1 = T.axis.spatial(512, i2_0_i0_i1_fused)
                            vk_fused_0 = T.axis.reduce(16, k_fused_0)
                            v_i2 = T.axis.spatial(8, i2_1)
                            C_rf_local[vk_fused_1, 0, 0, v_i1 * 8 + v_i2] = C_rf_local[vk_fused_1, 0, 0, v_i1 * 8 + v_i2] + V[0, 0, vk_fused_0 * 256 + vk_fused_1] * ((T.Cast("float16", T.bitwise_and(T.shift_right(W[v_i1, vk_fused_0 * 256 + vk_fused_1], T.Cast("uint32", (v_i1 * 8 + v_i2) % 8) * T.uint32(4)), T.uint32(15))) - T.float16(7)) * S[v_i1 // 4, vk_fused_0 * 256 + vk_fused_1])
                for ax1_ax2_ax3_fused_0 in range(1):
                    for ax0_fused in T.thread_binding(256, thread="threadIdx.x"):
                        for ax1_ax2_ax3_fused_1 in range(8):
                            with T.block("matmul"):
                                vk_fused_1 = T.axis.reduce(256, ax0_fused)
                                v_i1 = T.axis.spatial(512, i2_0_i0_i1_fused)
                                v_i2 = T.axis.spatial(8, ax1_ax2_ax3_fused_0 * 8 + ax1_ax2_ax3_fused_1)
                                with T.init():
                                    C[0, 0, v_i1 * 8 + v_i2] = T.float16(0)
                                C[0, 0, v_i1 * 8 + v_i2] = C[0, 0, v_i1 * 8 + v_i2] + C_rf_local[vk_fused_1, 0, 0, v_i1 * 8 + v_i2]

    # fmt: on

    target = Target("nvidia/geforce-rtx-3090-ti")
    with target:
        mod = dl.ApplyDefaultSchedule(dl.gpu.DecodeGEMV())(Before)  # pylint: disable=not-callable
    assert_structural_equal(mod, After)


def test_decode_gemv_4():
    # KN layout + N as decode dim
    # fmt: off
    @I.ir_module
    class Before:
        @T.prim_func
        def func(W: T.Buffer((4096, 512), "uint32"), S: T.Buffer((4096, 128), "float16"), V: T.Buffer((1, 1, 4096), "float16"), C: T.Buffer((1, 1, 4096), "float16")):
            T.func_attr({"global_symbol": "main", "tir.noalias": T.bool(True)})
            # with T.block("root"):
            B = T.alloc_buffer((4096, 4096), "float16")
            for i, j in T.grid(4096, 4096):
                with T.block("decode"):
                    v_i, v_j = T.axis.remap("SS", [i, j])
                    T.reads(W[v_i, v_j // 8], S[v_i, v_j // 32])
                    T.writes(B[v_i, v_j])
                    B[v_i, v_j] = (T.Cast("float16", T.bitwise_and(T.shift_right(W[v_i, v_j // 8], T.Cast("uint32", v_j % 8) * T.uint32(4)), T.uint32(15))) - T.float16(7)) * S[v_i, v_j // 32]
            for i0, i1, i2, k in T.grid(1, 1, 4096, 4096):
                with T.block("matmul"):
                    v_i0, v_i1, v_i2, v_k = T.axis.remap("SSSR", [i0, i1, i2, k])
                    T.reads(V[v_i0, v_i1, v_k], B[v_k, v_i2])
                    T.writes(C[v_i0, v_i1, v_i2])
                    with T.init():
                        C[v_i0, v_i1, v_i2] = T.float16(0)
                    C[v_i0, v_i1, v_i2] = C[v_i0, v_i1, v_i2] + V[v_i0, v_i1, v_k] * B[v_k, v_i2]


    @I.ir_module
    class After:
        @T.prim_func
        def func(W: T.Buffer((4096, 512), "uint32"), S: T.Buffer((4096, 128), "float16"), V: T.Buffer((1, 1, 4096), "float16"), C: T.Buffer((1, 1, 4096), "float16")):
            T.func_attr({"global_symbol": "main", "tir.is_scheduled": 1, "tir.noalias": T.bool(True)})
            C_rf_local = T.alloc_buffer((16, 1, 1, 4096), "float16", scope="local")
            for i2_0_i0_i1_fused_0 in T.thread_binding(32, thread="blockIdx.x"):
                for i2_0_i0_i1_fused_1 in T.thread_binding(16, thread="threadIdx.x"):
                    for k_fused_1 in T.thread_binding(16, thread="threadIdx.y"):
                        for i2_1_init in range(8):
                            with T.block("matmul_rf_init"):
                                vk_fused_1 = T.axis.spatial(16, k_fused_1)
                                v1 = T.axis.spatial(512, i2_0_i0_i1_fused_0 * 16 + i2_0_i0_i1_fused_1)
                                v2 = T.axis.spatial(8, i2_1_init)
                                C_rf_local[vk_fused_1, 0, 0, v1 * 8 + v2] = T.float16(0)
                        for k_fused_0, i2_1 in T.grid(256, 8):
                            with T.block("matmul_rf_update"):
                                vk_fused_1 = T.axis.spatial(16, k_fused_1)
                                v1 = T.axis.spatial(512, i2_0_i0_i1_fused_0 * 16 + i2_0_i0_i1_fused_1)
                                vk_fused_0 = T.axis.reduce(256, k_fused_0)
                                v2 = T.axis.spatial(8, i2_1)
                                C_rf_local[vk_fused_1, 0, 0, v1 * 8 + v2] = C_rf_local[vk_fused_1, 0, 0, v1 * 8 + v2] + V[0, 0, vk_fused_0 * 16 + vk_fused_1] * ((T.Cast("float16", T.bitwise_and(T.shift_right(W[vk_fused_0 * 16 + vk_fused_1, v1], T.Cast("uint32", (v1 * 8 + v2) % 8) * T.uint32(4)), T.uint32(15))) - T.float16(7)) * S[vk_fused_0 * 16 + vk_fused_1, v1 // 4])
                for ax1_ax2_ax3_fused_0 in T.thread_binding(16, thread="threadIdx.x"):
                    for ax0_fused in T.thread_binding(16, thread="threadIdx.y"):
                        for ax1_ax2_ax3_fused_1 in range(8):
                            with T.block("matmul"):
                                vk_fused_1 = T.axis.reduce(16, ax0_fused)
                                v1 = T.axis.spatial(512, i2_0_i0_i1_fused_0 * 16 + (ax1_ax2_ax3_fused_0 * 8 + ax1_ax2_ax3_fused_1) // 8)
                                v2 = T.axis.spatial(8, (ax1_ax2_ax3_fused_0 * 8 + ax1_ax2_ax3_fused_1) % 8)
                                with T.init():
                                    C[0, 0, v1 * 8 + v2] = T.float16(0)
                                C[0, 0, v1 * 8 + v2] = C[0, 0, v1 * 8 + v2] + C_rf_local[vk_fused_1, 0, 0, v1 * 8 + v2]

    # fmt: on

    target = Target("nvidia/geforce-rtx-3090-ti")
    with target:
        mod = dl.ApplyDefaultSchedule(dl.gpu.DecodeGEMV())(Before)  # pylint: disable=not-callable
    assert_structural_equal(mod, After)


def test_decode_gemv_sigmoid():
    # NK layout + K as decode dim
    # fmt: off
    @I.ir_module
    class Before:
        @T.prim_func
        def func(W: T.Buffer((4096, 512), "uint32"), S: T.Buffer((4096, 128), "float16"), V: T.Buffer((1, 1, 4096), "float16"), D: T.Buffer((1, 1, 4096), "float16")):
            T.func_attr({"global_symbol": "main", "tir.noalias": T.bool(True)})
            # with T.block("root"):
            B = T.alloc_buffer((4096, 4096), "float16")
            C = T.alloc_buffer((1, 1, 4096), "float16")
            for i, j in T.grid(4096, 4096):
                with T.block("decode"):
                    v_i, v_j = T.axis.remap("SS", [i, j])
                    T.reads(W[v_i, v_j // 8], S[v_i, v_j // 32])
                    T.writes(B[v_i, v_j])
                    B[v_i, v_j] = (T.Cast("float16", T.bitwise_and(T.shift_right(W[v_i, v_j // 8], T.Cast("uint32", v_j % 8) * T.uint32(4)), T.uint32(15))) - T.float16(7)) * S[v_i, v_j // 32]
            for i0, i1, i2, k in T.grid(1, 1, 4096, 4096):
                with T.block("matmul"):
                    v_i0, v_i1, v_i2, v_k = T.axis.remap("SSSR", [i0, i1, i2, k])
                    T.reads(V[v_i0, v_i1, v_k], B[v_i2, v_k])
                    T.writes(C[v_i0, v_i1, v_i2])
                    with T.init():
                        C[v_i0, v_i1, v_i2] = T.float16(0)
                    C[v_i0, v_i1, v_i2] = C[v_i0, v_i1, v_i2] + V[v_i0, v_i1, v_k] * B[v_i2, v_k]
            for i0, i1, i2 in T.grid(1, 1, 4096):
                with T.block("sigmoid"):
                    v_i0, v_i1, v_i2 = T.axis.remap("SSS", [i0, i1, i2])
                    T.reads(C[v_i0, v_i1, v_i2])
                    T.writes(D[v_i0, v_i1, v_i2])
                    D[v_i0, v_i1, v_i2] = T.sigmoid(C[v_i0, v_i1, v_i2])

    @I.ir_module
    class After:
        @T.prim_func
        def func(W: T.Buffer((4096, 512), "uint32"), S: T.Buffer((4096, 128), "float16"), V: T.Buffer((1, 1, 4096), "float16"), D: T.Buffer((1, 1, 4096), "float16")):
            T.func_attr({"global_symbol": "main", "tir.is_scheduled": 1, "tir.noalias": T.bool(True)})
            # with T.block("root"):
            C_local = T.alloc_buffer((1, 1, 4096), "float16", scope="local")
            C_rf_local = T.alloc_buffer((256, 1, 1, 4096), "float16", scope="local")
            for i2_i0_i1_fused in T.thread_binding(4096, thread="blockIdx.x"):
                for k_0_fused_1 in T.thread_binding(256, thread="threadIdx.x"):
                    with T.block("matmul_rf_init"):
                        vk_0_fused_1 = T.axis.spatial(256, k_0_fused_1)
                        v_i2 = T.axis.spatial(4096, i2_i0_i1_fused)
                        C_rf_local[vk_0_fused_1, 0, 0, v_i2] = T.float16(0)
                    for k_0_fused_0, k_1 in T.grid(2, 8):
                        with T.block("matmul_rf_update"):
                            vk_0_fused_1 = T.axis.spatial(256, k_0_fused_1)
                            v_i2, vk_0_fused_0, vk_1 = T.axis.remap("SRR", [i2_i0_i1_fused, k_0_fused_0, k_1])
                            C_rf_local[vk_0_fused_1, 0, 0, v_i2] = C_rf_local[vk_0_fused_1, 0, 0, v_i2] + V[0, 0, (vk_0_fused_0 * 256 + vk_0_fused_1) * 8 + vk_1] * ((T.Cast("float16", T.bitwise_and(T.shift_right(W[v_i2, vk_0_fused_0 * 256 + vk_0_fused_1], T.Cast("uint32", ((vk_0_fused_0 * 256 + vk_0_fused_1) * 8 + vk_1) % 8) * T.uint32(4)), T.uint32(15))) - T.float16(7)) * S[v_i2, (vk_0_fused_0 * 256 + vk_0_fused_1) // 4])
                for ax1_ax2_ax3_fused in range(1): # pylint: disable=unused-variable
                    for ax0_fused in T.thread_binding(256, thread="threadIdx.x"):
                        with T.block("matmul"):
                            vk_0_fused_1 = T.axis.reduce(256, ax0_fused)
                            v_i2 = T.axis.spatial(4096, i2_i0_i1_fused)
                            with T.init():
                                C_local[0, 0, v_i2] = T.float16(0)
                            C_local[0, 0, v_i2] = C_local[0, 0, v_i2] + C_rf_local[vk_0_fused_1, 0, 0, v_i2]
                with T.block("sigmoid"):
                    v_i2 = T.axis.spatial(4096, i2_i0_i1_fused)
                    D[0, 0, v_i2] = T.sigmoid(C_local[0, 0, v_i2])

    # fmt: on

    target = Target("nvidia/geforce-rtx-3090-ti")
    with target:
        mod = dl.ApplyDefaultSchedule(dl.gpu.DecodeGEMV())(Before)  # pylint: disable=not-callable
    assert_structural_equal(mod, After)


def test_decode_gemv_1_fp32():
    # NK layout + K as decode dim
    # fmt: off
    @I.ir_module
    class Before:
        @T.prim_func
        def func(W: T.Buffer((4096, 512), "uint32"), S: T.Buffer((4096, 128), "float16"), V: T.Buffer((1, 1, 4096), "float16"), C: T.Buffer((1, 1, 4096), "float16")):
            T.func_attr({"global_symbol": "main", "tir.noalias": T.bool(True)})
            # with T.block("root"):
            B = T.alloc_buffer((4096, 4096), "float16")
            C_fp32 = T.alloc_buffer((1, 1, 4096), "float32")
            for i, j in T.grid(4096, 4096):
                with T.block("decode"):
                    v_i, v_j = T.axis.remap("SS", [i, j])
                    T.reads(W[v_i, v_j // 8], S[v_i, v_j // 32])
                    T.writes(B[v_i, v_j])
                    B[v_i, v_j] = (T.Cast("float16", T.bitwise_and(T.shift_right(W[v_i, v_j // 8], T.Cast("uint32", v_j % 8) * T.uint32(4)), T.uint32(15))) - T.float16(7)) * S[v_i, v_j // 32]
            for i0, i1, i2, k in T.grid(1, 1, 4096, 4096):
                with T.block("matmul"):
                    v_i0, v_i1, v_i2, v_k = T.axis.remap("SSSR", [i0, i1, i2, k])
                    T.reads(V[v_i0, v_i1, v_k], B[v_i2, v_k])
                    T.writes(C_fp32[v_i0, v_i1, v_i2])
                    with T.init():
                        C_fp32[v_i0, v_i1, v_i2] = T.float16(0)
                    C_fp32[v_i0, v_i1, v_i2] = C_fp32[v_i0, v_i1, v_i2] + T.Cast("float32", V[v_i0, v_i1, v_k]) * T.Cast("float32", B[v_i2, v_k])
            for i0, i1, i2 in T.grid(1, 1, 4096):
                with T.block("cast"):
                    v_i0, v_i1, v_i2 = T.axis.remap("SSS", [i0, i1, i2])
                    T.reads(C_fp32[v_i0, v_i1, v_i2])
                    T.writes(C[v_i0, v_i1, v_i2])
                    C[v_i0, v_i1, v_i2] = T.Cast("float16", C_fp32[v_i0, v_i1, v_i2])


    @I.ir_module
    class After:
        @T.prim_func
        def func(W: T.Buffer((4096, 512), "uint32"), S: T.Buffer((4096, 128), "float16"), V: T.Buffer((1, 1, 4096), "float16"), C: T.Buffer((1, 1, 4096), "float16")):
            T.func_attr({"global_symbol": "main", "tir.is_scheduled": 1, "tir.noalias": T.bool(True)})
            # with T.block("root"):
            C_fp32_local = T.alloc_buffer((1, 1, 4096), scope="local")
            C_fp32_rf_local = T.alloc_buffer((256, 1, 1, 4096), scope="local")
            for ax0_fused in T.thread_binding(4096, thread="blockIdx.x"):
                for ax1_0_fused_1 in T.thread_binding(256, thread="threadIdx.x"):
                    with T.block("matmul_rf_init"):
                        vax1_0_fused_1, v0 = T.axis.remap("SS", [ax1_0_fused_1, ax0_fused])
                        T.reads()
                        T.writes(C_fp32_rf_local[vax1_0_fused_1, 0, 0, v0])
                        C_fp32_rf_local[vax1_0_fused_1, 0, 0, v0] = T.float32(0)
                    for ax1_0_fused_0, ax1_1 in T.grid(2, 8):
                        with T.block("matmul_rf_update"):
                            vax1_0_fused_1, v0, vax1_0_fused_0, vax1_1 = T.axis.remap("SSRR", [ax1_0_fused_1, ax0_fused, ax1_0_fused_0, ax1_1])
                            C_fp32_rf_local[vax1_0_fused_1, 0, 0, v0] = C_fp32_rf_local[vax1_0_fused_1, 0, 0, v0] + T.Cast("float32", V[0, 0, (vax1_0_fused_0 * 256 + vax1_0_fused_1) * 8 + vax1_1]) * T.Cast("float32", (T.Cast("float16", T.bitwise_and(T.shift_right(W[v0, vax1_0_fused_0 * 256 + vax1_0_fused_1], T.Cast("uint32", ((vax1_0_fused_0 * 256 + vax1_0_fused_1) * 8 + vax1_1) % 8) * T.uint32(4)), T.uint32(15))) - T.float16(7)) * S[v0, (vax1_0_fused_0 * 256 + vax1_0_fused_1) // 4])
                for ax1_fused in range(1):
                    for ax0_fused_1 in T.thread_binding(256, thread="threadIdx.x"):
                        with T.block("matmul"):
                            vax1_0_fused_1, v0 = T.axis.remap("RS", [ax0_fused_1, ax0_fused])
                            T.reads(C_fp32_rf_local[vax1_0_fused_1, 0, 0, v0])
                            T.writes(C_fp32_local[0, 0, v0])
                            with T.init():
                                C_fp32_local[0, 0, v0] = T.float32(0)
                            C_fp32_local[0, 0, v0] = C_fp32_local[0, 0, v0] + C_fp32_rf_local[vax1_0_fused_1, 0, 0, v0]
                with T.block("cast"):
                    v0 = T.axis.spatial(4096, ax0_fused)
                    T.reads(C_fp32_local[0, 0, v0])
                    T.writes(C[0, 0, v0])
                    C[0, 0, v0] = T.Cast("float16", C_fp32_local[0, 0, v0])

    # fmt: on

    target = Target("nvidia/geforce-rtx-3090-ti")
    with target:
        mod = dl.ApplyDefaultSchedule(dl.gpu.DecodeGEMV())(Before)  # pylint: disable=not-callable
    assert_structural_equal(mod, After)


if __name__ == "__main__":
    test_decode_gemv_1()
    test_decode_gemv_2()
    test_decode_gemv_3()
    test_decode_gemv_4()
    test_decode_gemv_sigmoid()
    test_decode_gemv_1_fp32()