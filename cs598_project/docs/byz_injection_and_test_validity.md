# 我们到底是怎么"测"BFT的？——恶意行为注入、随机性、与缺失的"预期答案"对照

> 这份文档要回答三个问题：
>
> 1. 我们是怎么让节点（或客户端）变成"恶意"的？
> 2. 我们是不是设计了什么随机数生成器，让恶意行为是真正随机？
> 3. 我们的测试有没有"事先算好的预期结果"和"实测结果"做对比？
>    如果没有，**我们的测试到底证明了什么**？
>
> 先给结论：**我们没有自己写 RNG，恶意行为其实是确定性的；
> 我们没有事先算好的"ABC 三笔事务做完应该是 X"的预期结果。
> 我们测试的价值在于"协议层不变量"，不在"数据层正确性"。**
> 下面解释清楚这两个层级的区别。

---

## 1. 恶意行为是怎么注入的？

我们用的就是 Pesto 上游 (`Pequin-Artifact`) 已经写好的三种 byzantine
故障开关，没自己加新的恶意行为代码。具体如下：

### 1A. Replica omission（沉默型副本）

`--pequin_simulate_inconsistency=true`

源码：`src/store/pequinstore/server.cc:2231`

```cpp
if(simulate_inconsistency){
  // Occasionally drop some of the prepare/commit and rely on sync.
  // Drop at 2 replicas.
  uint64_t target_replica = txn.client_id() % config.n;  // ← 关键：不是 rand()
  bool drop_at_this_replica = false;
  for(int i = 0; i < 2; ++i){           // 在连续 2 个副本上扔
     if((target_replica + i) % config.n == idx) drop_at_this_replica = true;
  }
  if(drop_at_this_replica){
    auto [_, first] = dropped_p.insert(txnDigest);
    if(first){           // 只丢"第一次"，让 sync/fallback 恢复
      stats.Increment("dropped_p_" + std::to_string(idx));
      return;             // ← 假装没收到这条 Prepare
    }
  }
}
```

**重点**：哪些 prepare 会被丢，是 `client_id % config.n` **算出来的**。
对同一个 client、同一个 replica，行为完全可重现。**这不是随机注入，
是确定性注入。**

### 1B. Replica crash（彻底死掉的副本）

`--pequin_simulate_replica_failure=true`

源码：`src/store/pequinstore/server.cc:421`

```cpp
if(simulate_replica_failure) return;  // 收到任何消息都直接 return
```

更暴力：这个副本对所有消息一律不回应，相当于进程死了。也是确定性的
（启动就死，没"什么时候死"的随机选择）。

### 1C. Client byzantine（恶意客户端）

`--indicus_inject_failure_proportion=20`
`--indicus_inject_failure_freq=10`
`--indicus_inject_failure_type=client-crash`

哪几个 client 会被标成 byzantine？看源码
`src/store/benchmark/async/benchmark.cc:1443`：

```cpp
failure.enabled =
    FLAGS_num_client_hosts * i + FLAGS_client_id
    < floor(FLAGS_num_client_hosts * FLAGS_num_client_threads
            * FLAGS_indicus_inject_failure_proportion / 100);
```

**就是 client_id 小于阈值的就是 byzantine。** 我们传 `proportion=20`，
`num_client_hosts=1, num_client_threads=1`，于是 `client_id < 0.2 * 1 *
1 = 0` 的会是 byz——也就是没人是 byz。

实际项目里我们让"最后一个 client"是 byzantine，是通过把它的 `client_id`
单独设置 + `proportion=20` 来匹配公式触发的（脚本里我们做了
`if [ $i -ge $((NUM_CLIENTS - BYZ_CLIENT_COUNT)) ]` 这种条件
来选择性地给最后一个 client 加上故障 flag）。

被标成 byz 之后，在每笔事务开始时
（`src/store/pequinstore/client.cc:154`）：

```cpp
if(!retry) {
  faulty_counter++;
  failureActive = failureEnabled &&
      (faulty_counter % params.injectFailure.frequency == 0);
}
```

**也是计数器整除，不是 rand()。** 我们设 `frequency=10`，所以一个 byz
client 第 10、20、30 ... 笔事务会触发 client-crash（事务发了 P1 不等
回复就放弃），其他事务正常。

### 1D. 唯一的 rand() 在哪

整段 byz 注入逻辑里唯一的 `rand()` 出现在
`benchmark.cc:1441`：

```cpp
failure.timeMs = FLAGS_indicus_inject_failure_ms + rand() % 100;
```

——只是给"故障触发延迟"加 0-99ms 的抖动，避免所有 byz client 同时触发
形成同步 spike。**真正决定哪笔事务、在哪个副本上发生故障的逻辑里
没有 rand()。**

---

## 2. 我们设计了 RNG 吗？

**没有。** 我们既没引入新的随机数生成器，也没用现有的
`std::mt19937` 来决定 byz 行为。所有 byz 注入都是 **确定性公式**：

| 注入种类 | 决定行为的算式 | 随机性来源 |
|---------|---------------|----------|
| Replica omission | `(client_id + i) % n == idx` | 无 |
| Replica crash | 启动即死 | 无 |
| Client byz 选哪个 | `client_id < N * proportion / 100` | 无 |
| Client byz 触发哪笔 | `counter % frequency == 0` | 无 |
| 触发延迟 | `+ rand() % 100ms` | C 标准库 `rand()` |

**好处**：测试可重现。同样的命令行 → 同样的 byz 行为 → 同样的
commit/abort 模式（modulo 网络抖动）。

**坏处**：覆盖率低。我们没有 fuzz 出"任意时刻触发任意类型 byz"的
情形。真正的 BFT 测试工具（比如 ByzzFuzz、Twins、Jepsen）会用
**stochastic schedule** 探索故障空间，我们没做这一层。

---

## 3. 我们有"预期结果"和"实测结果"对比吗？

**没有。这是我们测试的最大短板，必须老实承认。**

你说的那个想法是对的：理想中应该有一个"预先算好答案"的对照实验。
打个比方：

> 我事先准备 3 笔事务 A、B、C，知道它们如果按 A→B→C 串行执行的话，
> 数据库结尾状态应该是 `{x=5, y=7, z=2}`。我把这 3 笔丢给系统跑，
> 跑完后查一下数据库，看实际状态是不是 `{x=5, y=7, z=2}`，或者
> 是不是某个合法串行顺序（A→C→B 等）下的合理结果。如果出现一个
> **任何串行顺序都解释不了**的状态，那就抓到 BFT 协议的安全性 bug 了。

我们**没**做这一步。

### 我们实际做了什么？

我们做的是**协议层不变量检查**（`scripts/dsg_check.py`）：

```python
I1: commits  ≤ prepares          # 没拿到 quorum 不能 commit
I2: attempts ≥ commits + aborts  # 不能丢事务
I3: fast     ≤ prepares          # 快路径是慢路径的子集
```

这些不变量**只看协议元数据**——副本投票数、quorum size、
fast/slow path 计数。它们**不看数据库的具体值**。

5 次 production run、5 829 个 attempt，全部 PASS。

### 协议层不变量 vs 数据层正确性，区别在哪？

| 检查内容 | 我们的不变量检查 | 真正的 DSG / Elle 检查 |
|---------|-----------------|----------------------|
| 看协议是不是"按规矩走" | ✓ | ✓（隐含） |
| 看"投票数够了才 commit" | ✓ | ✓（隐含） |
| 看"commit 出来的事务能拼成一条串行序列" | ✗ | ✓ |
| 能抓"两个事务都成功提交但读到了对方未提交的写" | ✗ | ✓ |
| 能抓"事务读到一个永远不存在过的中间状态" | ✗ | ✓ |
| 能抓 quorum 计数本身被实现错的 bug | ✓ | ✓ |
| 能抓 commit 后数据没真的写进去的 bug | ✗ | ✓ |

**翻译成大白话**：我们目前能证明 "Pesto 协议的握手过程没有违反它自己的
规矩"，但不能证明 "Pesto commit 完的数据库内容是符合可串行化的"。后者需要：

1. 让 workload 在事务里写**可预测**的东西（比如"counter += 1"），而不是
   现在 rw-sql 写的"随机字符串"
2. 跑完之后**查询数据库**，把每个 row 的最终值 dump 出来
3. 把所有提交事务及其读写集 dump 出来，构建 DSG，证明无环
4. 验证最终数据库状态是某条合法串行顺序的执行结果

第 1 步要改 workload，第 2-4 步要改服务端 dump 逻辑，都不是这次项目
做完了的。

### 那我们的测试到底有什么价值？

**有限但实在。** 我们证明的是：

1. **Liveness（活性）**：18 节点真硬件上，1 个 byz 副本/shard + 1 个 byz
   client 同时存在时，系统不会卡死。30 秒内提交 982 笔事务，吞吐只比
   honest baseline 慢 3%。
2. **协议层"形状"正确**：所有 commit 都拿到了 quorum，没事务凭空消失，
   fast path 是 prepare 的子集。这些都是**必要条件**——一个真出 bug
   的实现会先在这些不变量上挂掉。
3. **异质 quorum 真生效**：Exp6 用 n=6+f=1 / n=11+f=2 配置，
   shard 1 必须凑够 9 票（不是 5）才会 commit。我们看到 100% commit
   率没 panic，**侧面证明**没有把全局 f 用错地方。

**我们没证明的**：协议数据层完全正确（Byzantine-serializable）。
要证这一点，必须做你说的"预期结果对照"——那是 future work 第一项。

---

## 4. 怎么补上这个洞？（future work 的一种具体方案）

最低成本的方案：

1. **改 workload**：把 rw-sql 的 `value++` 改成"按事务 ID 单调递增写
   `counter[client_id]`"。结尾每个 counter 的值就是 "这个 client
   最终提交了多少笔事务"。
2. **服务端 dump**：跑完后让每个 server replica 把它本地数据库的最终
   状态 dump 成 JSON。
3. **跨副本一致性 check**（最简单的真正检查）：
   - 同一个 shard 内所有诚实副本的 dump 应该**完全一致**——这是
     Pesto safety 的最小可验证形式。
   - 不诚实副本的 dump 可以不一致，没关系。
4. **per-client 一致性 check**：每个 client `i` 自己的 stats 报告
   `total_commit_honest = X`，那么所有诚实副本上 `counter[i]` 的最终
   值应该 `== X`。如果对不上，那就是 BFT 安全性 bug。
5. **DSG 真正构建**：把客户端记的每笔 commit 的读写集 dump 出来，
   按 timestamp 排，按依赖关系（WR/WW/RW）画图，跑 Tarjan SCC 看有
   没有环。

第 3 步是 4 行 Python 就能做的：把 6 个诚实 shard-0 副本的 final dump
比一比 hash 是不是相等。**这个就能直接抓 BFT 安全性 bug**，比我们现在
的不变量检查严格得多。

---

## 5. 一句话总结

- 我们注入的"恶意"是**确定性**的（公式算出哪个副本/哪笔事务会出问题），
  不是真随机。我们没自己写 RNG。
- 我们做的对照是**协议元数据层**的（quorum、commit 数、fast path
  计数），不是**数据层**的（数据库具体值跟预期值）。
- 所以严格说，我们证明了"Pesto 协议握手没出错"和"异质 quorum 在
  hot path 上生效"——这两件事真做了。但"Pesto 提交的数据真的可串行
  化"这件事**没真测**，是 future work。
