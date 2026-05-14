# BFT 测试框架调研 — Pesto 扩展项目能直接用什么？

> 上一份文档（`byz_injection_and_test_validity.md`）承认了我们最大的洞：
> 没做"数据层可串行化"对照。这份文档调研业界做这件事现成的工具，
> 给出可执行的采用建议。

## TL;DR — 三句话决策

1. **必须采用：Elle (`elle-cli`)** — 黑盒可串行化检查器，1–2 天即可
   上线，能直接补上数据层盲区。
2. **强烈推荐：Twins 思想（自实现，~1 周）** — 不照搬 DiemBFT-Twins
   仓库（不维护），借鉴"同身份双胞胎副本"思路在 Pesto 加 flag。
3. **不要采用**：ByzzFuzz（绑死 pbft-java）、BFTBrain/BFTGym（性能优化
   用，非安全）、Bedrock（统一性能平台，非安全 Bug 挖掘）。

---

## 1. Elle (Kingsbury & Alvaro, VLDB'20) — **强烈推荐采用**

- **开源**：是
  - 主库：https://github.com/jepsen-io/elle (Clojure)
  - **关键工具 `elle-cli`**（语言无关 CLI 包装）：
    https://github.com/ligurio/elle-cli
- **输入格式**：EDN 或 **JSON** 操作历史。每条操作形如：
  ```
  {:type :invoke, :f :append, :process 2, :value [:append "x" 1], :index 0}
  {:type :ok,     :f :append, :process 2, :value [:append "x" 1], :index 1}
  ```
- **检查的异常**（这些正是当前 Python 不变量检查器看不见的）：
  - **G0** 写循环
  - **G1a/b/c** 脏读 / 中间读 / 循环信息流
  - **G-Single** 读偏斜
  - **G2** 反依赖循环
  - 内部不一致、丢失更新、重复写
- **支持的 workload 模型**：`list-append`、`rw-register`、`bank`、
  `counter`、`long-fork`、`set`、`cas-register`、`sequential`
- **接到 Pesto 上的具体步骤**（**1–2 天**）：
  1. 在 Pesto 客户端里包一层 logger：每个 SQL 事务的 invoke/ok/fail 写
     一条 JSON 行（带 `:process`, `:time`, `:index`, `:value`）。**注意要
     记 invoke 和 complete 两条**——Elle 需要这两个时间点。
  2. 选 **`list-append`** 模型最简单：把 SQL 表当 key→list 映射，事务里
     只做 `INSERT INTO t(k, seq, v) VALUES (...)` 当 append、
     `SELECT v FROM t WHERE k=? ORDER BY seq` 当 read-list。
  3. 跑 `java -jar elle-cli-0.1.8-standalone.jar --model list-append history.json`。
     返回 `true`/`false`/`:unknown`，并给出反例图。
  4. 把现有的 `--pequin_simulate_inconsistency` /
     `--pequin_simulate_replica_failure` 注入打开后跑同一个 workload，
     期望 Elle 抓到 G2/G-Single。
- **抓得到、我们现在抓不到的 Bug**：丢失更新、写偏斜、读偏斜、跨事务
  循环依赖、中间状态被读到（G1b）、回滚事务被读到（G1a）。
- **风险/限制**：Elle 假设客户端忠诚——拜占庭客户端不在它的模型里。
  我们的故障注入主要在 replica 端，正好契合。

---

## 2. Jepsen 框架本体 — **不建议作为主框架**

- 开源：https://github.com/jepsen-io/jepsen (Clojure)
- **BFT 的局限**：Jepsen 的 nemesis 模型本质是 **crash + network
  partition + clock skew**，**没有原生拜占庭节点（伪造消息、双签）模型**。
  社区做 TiDB/CockroachDB/FoundationDB 的 Jepsen 测试都是 crash-fault
  下的可串行化验证。
- **接到 Pesto 上的代价**：写 Clojure client + nemesis + 部署脚本
  ≈ **1–2 周**，对学期末项目 ROI 太低。
- **结论**：**跳过 Jepsen 框架，只用 Elle**。这是社区里大家其实都在做
  的事——许多团队不跑完整 Jepsen，只用 `elle-cli` 检查自己导出的历史。

---

## 3. ByzzFuzz (Winter et al., ICSE'23) — **不建议采用**

- 开源：https://github.com/burcuku/byzzfuzz-pbft，但 **死绑 `pbft-java`
  这一个具体实现**。
- 语言：Java（97%）。
- 接到 Pesto 上的代价：要把 Pesto 的 C++ 消息层重写成可被 Java tester
  拦截 = 重写 Pesto 网络层 = **3–6 周以上**。
- **结论**：思想（小范围消息变异 + round-bounded 故障）值得借鉴写进
  related work，**不要复用代码**。

---

## 4. Twins (Bano et al., OPODIS'21) — **推荐借鉴思想（自实现）**

- 论文：https://arxiv.org/abs/2004.10617
- 官方实现：是 Diem 内部 CI 一部分，**未单独开源**。
- 第三方复现：https://github.com/druuuu/DiemBFT-Twins（Python/DistAlgo，
  学生项目，0 star，无维护）→ 不能直接用。
- **核心思想**：实例化某副本的"双胞胎"——**两个进程共享同一个身份和
  密钥**，对系统其他部分看起来就是"同一个节点表现得很可疑"。Twins 自动
  覆盖：(i) leader equivocation、(ii) double voting、(iii) 状态丢失。
- **接到 Pesto 上的具体步骤**（**3–7 天**）：
  1. 在 Pesto 启动脚本加 `--pequin_twin_of=<replica_id>` flag：让一个
     新进程加载和 replica X 相同的私钥/身份。
  2. 让它和 replica X 各自独立处理客户端请求并独立生成 PREPARE/COMMIT。
  3. 配置网络分区，让 quorum 一半看到 twin A、一半看到 twin B → 自动
     产生 equivocation。
  4. 用 Elle 检查输出历史是否串行化。
- **能抓的 Bug**：leader equivocation 漏洞、forked log、view-change 后
  状态不一致——**这些是异构 membership 扩展最可能的 Bug 来源**。
- **结论**：**值得做**。和 Elle 是天然搭配（Twins 制造拜占庭，Elle 验证
  安全）。Pesto 既然已经有 `--pequin_simulate_replica_failure`，加
  twin flag 是同一个抽象层。

---

## 5. BFTBrain (NSDI'25) & BFTGym (VLDB'24) — **不适用**

- 仓库：
  - https://github.com/JeffersonQin/BFTBrain
  - https://github.com/JeffersonQin/BFTGym
- **本质**：**性能优化框架**——RL agent 在不同 BFT 协议（PBFT 等）之间
  动态切换以优化吞吐/延迟。
- **不适合的原因**：
  - 不做安全 Bug 挖掘，只做性能切换
  - 只测自己 pool 里的 BFT 实现，不能拿来测 Pesto
  - 我们要找 safety Bug，BFTBrain 关心找最快协议——**问题域错位**
- **结论**：related work 里提一句对比，**不要采用**。

---

## 6. Bedrock (Amiri et al., NSDI'24, Outstanding Paper) — **不适用**

- 论文：https://arxiv.org/abs/2205.04534
- **本质**：**统一的 BFT 协议设计/比较平台**——把多种 BFT 协议
  （PBFT, Zyzzyva, SBFT, HotStuff 等）放在同一框架下做**性能**对比。
- **不适合**：和 BFTBrain 一样，是 performance benchmarking，不是
  safety bug finding。需要把 Pesto 重新实现到 Bedrock 抽象里才能用，
  得不偿失。

---

## 7. 其他社区工具速览

| 工具 | 用途 | 对我们 |
|------|------|-------|
| **Knossos** (jepsen-io/knossos) | 线性化检查（单 register） | 比 Elle 弱、慢，已被 Elle 全面取代 |
| **Porcupine** (anishathalye/porcupine) | Go 写的线性化检查器 | 仅线性化，不做事务，不如 Elle |
| **MoneTa / IsoDiff** | SQL 隔离级别异常检测 | 学术原型，没维护好的工具 |
| **Maelstrom** (jepsen-io/maelstrom) | 教学用 BFT/共识 | 玩具协议，不能测 Pesto |
| **Coyote / TLA+ TLC** | 模型检查 | 需重新建模 Pesto 协议，工作量过大 |

---

## 行动建议（按优先级）

### P0 — 本周做完（共 3–4 天）

1. **Elle 接入**（1–2 天）
   - Clone https://github.com/ligurio/elle-cli，`lein uberjar`
   - Pesto 客户端加 JSON history logger（invoke/ok/fail，带
     `:process`, `:time`, `:index`, `:value`）
   - 设计 `list-append` workload：单表
     `(k INT, seq INT, v INT, PRIMARY KEY(k,seq))`，事务里只做 append 和
     read-list
   - 跑 `--model list-append`，先在无故障基线下确认输出 `true`，再开
     `--pequin_simulate_inconsistency` 看 Elle 是否抓到 G2/G-Single
2. **保留现有 Python 不变量脚本**作为快速烟雾测试。Elle 是"重武器"，
   不变量脚本是"金丝雀"。

### P1 — 第二周（如时间允许，3–7 天）

3. **Twins 风格自实现**：在 Pesto 加 `--pequin_twin_of=<id>` flag，
   造出 equivocation。和 P0 的 Elle 串起来跑。

### P2 — 写进论文 Related Work，**不实现**

- ByzzFuzz（small-scope 消息变异思想）
- BFTBrain / BFTGym（性能 RL，对比说明我们目标不同）
- Bedrock（统一平台，对比说明我们关心 safety 而非 perf）
- Jepsen 框架（说明用了它的核心检查器 Elle，但跳过了 nemesis 框架因为
  BFT 模型不匹配）

---

## 现状到升级方案的映射表

| 现状 | 升级后 |
|------|-------|
| `--pequin_simulate_inconsistency` → Python 检查 commits ≤ prepares | 同故障 → **Elle** 检查 SQL 串行化 |
| `--pequin_simulate_replica_failure` → Python 检查 attempts ≥ commits+aborts | 同故障 → **Elle** 检查是否产生分叉读 |
| `--indicus_inject_failure_*` → 客户端不变量 | 加 **`--pequin_twin_of`** → Elle 抓 equivocation 导致的循环依赖 |
| 确定性触发器（`client_id % n`、`counter % freq`） | 保留确定性便于复现；twin flag 也用确定性 |

---

## 为什么这条路对

1. **Elle 不是研究原型**——它已经在 TiDB、CockroachDB、FoundationDB、
   YugabyteDB、MongoDB 等生产数据库上抓到过真 Bug。我们用 Elle 等于
   接入了一个被工业界反复打磨过的检查器。
2. **不重新发明轮子**——我们之前 `dsg_check.py` 那套不变量虽然有用，
   但没法验证数据层可串行化。Elle 完美补上这块，且不需要我们自己再
   实现 DSG 算法。
3. **学期末 deliverable 切实**——P0（仅 Elle）2 天就能产出"我们用 Elle
   做黑盒可串行化验证，发现/未发现 X 类异常"这一句话写进论文。
4. **Twins 思想和 Elle 天然组合**——Twins 是"造拜占庭"，Elle 是"验证
   安全"，两者拼起来是 BFT 安全测试的黄金搭档。

## 引用

- [Elle (jepsen-io/elle)](https://github.com/jepsen-io/elle)
- [elle-cli (ligurio/elle-cli)](https://github.com/ligurio/elle-cli)
- [Jepsen 主页](https://jepsen-io.github.io/jepsen/)
- [ByzzFuzz 论文](https://gleissen.github.io/papers/byzzfuzz.pdf)
- [byzzfuzz-pbft 仓库](https://github.com/burcuku/byzzfuzz-pbft)
- [Twins 论文 (arXiv)](https://arxiv.org/abs/2004.10617)
- [BFTBrain (NSDI'25)](https://www.usenix.org/conference/nsdi25/presentation/wu-chenyuan)
- [BFTBrain 仓库](https://github.com/JeffersonQin/BFTBrain)
- [Bedrock (NSDI'24)](https://www.usenix.org/conference/nsdi24/presentation/amiri)
- [Bedrock arXiv](https://arxiv.org/abs/2205.04534)
