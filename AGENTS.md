# 开发约定

本文件记录仓库当前的开发、测试和文档约定，供维护者和自动化开发工具共同参考。

## 项目事实

- 项目使用 Python 3.11 或更高版本
- 依赖和虚拟环境推荐由 `uv` 管理
- 当前仓库没有 Git submodule
- 默认输出是按 ETF 和交易日分区的 Parquet
- 公开命令为 `etf-min` 和 `etf-min-check`
- 公开兼容函数包括 `fetch_etf_minute_range()`、`fetch_etf_minute()`、`fetch_symbol_range()` 和 `write_partition()`

仪表盘、日线数据、指标计算、策略和数据平台发布流程属于外部项目。本仓库不应为了这些下游需求直接引入前端或业务分析逻辑。

## 模块职责

- `cli.py` 负责参数解析和组件组装
- `universe.py` 负责 ETF 代码标准化和标的集合生成
- `engine.py` 负责并发、任务启动限速、重试和断点状态
- `fetcher.py` 负责单只 ETF 的抓取编排和公开兼容函数
- `providers.py` 负责第三方行情接口、回退链路和字段标准化
- `storage.py` 负责分区判断和 Parquet 写入
- `models.py` 放置共享数据模型
- `check.py` 提供在线健康检查

保持依赖方向简单。网络适配器不应反向依赖 CLI 或批量调度器。

## 安装开发依赖

```bash
uv sync --locked --extra dev
```

修改依赖声明后运行：

```bash
uv lock
```

`pyproject.toml` 和 `uv.lock` 应一起提交。

## 提交前检查

本地应运行：

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked ty check
uv run --locked pytest -q --cov=etf_minute_fetcher --cov-report=term-missing
uv run --locked pip-audit
uv build
```

覆盖率下限为 80%。CI 会在 Python 3.11 和 3.14 上运行测试。

不要为了让检查变绿而随意增加全局忽略规则。静态检查指出真实问题时优先修代码。确实需要宽泛异常捕获时，应让它出现在明确的边界位置，并用简短注释说明原因。

## 测试要求

新增或修改行为时同步补测试，重点覆盖：

- CLI 参数组合和退出码
- 断点恢复与任务条件变化
- 行情源异常、空结果和回退顺序
- 第三方返回字段变化
- 分区跳过和覆盖逻辑
- 健康检查结果

单元测试不要依赖实时网络。第三方行情响应应使用最小样本、monkeypatch 或测试替身。在线接口可用性由 `etf-min-check` 单独验证。

修复生产问题时，先写能复现问题的测试，再修改实现。对于第三方接口字段变化，尽量保留一个精简后的响应样本，避免只测试自己构造的理想 DataFrame。

## 类型和接口

公共函数的返回结构应有明确类型。结构固定的字典优先使用 `TypedDict`、数据类或其他静态可检查的类型，减少在调度层传播 `dict[str, Any]`。

`Any` 适合 JSON 断点内容等天然动态的数据边界。不要把它当成解决类型报错的快捷方式。

已有公开兼容函数需要谨慎删除或改签名。确认仓库内外都没有调用方，并在发布说明中明确破坏性变化后，再考虑清理。

## 异常处理

第三方数据源、线程任务边界和健康检查需要把不可控异常转换成项目自己的失败结果，因此这些位置可以捕获 `Exception`。

普通业务函数应尽量捕获能够明确处理的异常类型。不要在深层函数吞掉异常后只返回空数据，这会把网络故障和真实空行情混为一类。

## 抽象和文件拆分

当前 `MinuteDataProvider`、`BarStorage` 和 `UniverseProvider` 对应真实替换点，可以保留。

不要提前增加 Service、Repository、Factory 等层级。一个小型数据抓取工具很容易被架构名词淹没，最后找一行请求代码要穿过五个文件，谁都没有因此获得奖金。

`providers.py` 目前集中放置少量行情源和共享解析逻辑。只有在新增更多来源、某个来源出现大量专属代码或测试边界明显恶化时，再按来源拆文件。

## 文档写作

说明文档以中文为主，技术名称、类名、参数名和字段名保留必要的英文，并使用行内代码标记。

中文正文遵循这些习惯：

- 使用中文逗号、句号、冒号和括号
- 尽量直接陈述事实
- 少用翻译腔和中英夹杂的抽象词
- 避免没有必要的双引号
- 避免强调标记堆叠
- 避免分号和破折号
- 列表项可以省略句末标点，长段落使用完整句子

行为、参数、退出码、数据源顺序或目录结构发生变化时，同步检查：

```text
README.md
AGENTS.md
docs/
```

文档中的示例命令必须能对应当前 CLI。删除参数或功能后，应同时删除旧示例，避免让历史说明继续扮演活文档。

## 数据安全

以下生成物不提交到 Git：

```text
*.parquet
.download-checkpoint.json
.download-summary.json
.coverage
htmlcov/
```

写入正式 Parquet 和 JSON 状态文件时应保留原子替换策略，降低进程中断留下半成品的风险。

## 外部仓库

当前仓库没有 `.gitmodules`，根目录也没有 gitlink。文档中提到的其他仓库都视为外部系统。

如果以后真的引入 submodule，需要同时更新 README、本文档、CI checkout 配置和本地初始化说明。仅仅在文档里提到另一个仓库，不构成 submodule 关系。
