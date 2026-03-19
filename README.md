# FellowFinder

按配置执行如下流程：

1. 从目标学者的 Google Scholar 主页抓取论文列表。
2. 按标题关键词筛选目标论文，支持 `and` / `or`。
3. 用 OpenAlex 查找这些论文及其引用文章。
4. 检查引用文章作者是否在官方/机构页面中出现 Fellow 头衔，并结合作者单位做同名消歧。
5. 输出 `output/findings.json` 和 `output/findings.csv`。

## 安装

```bash
uv sync
```

## 运行

```bash
uv run python main.py --config config.toml
```

## 配置说明

### 基础搜索配置

- `search.scholar_profile_url`: 被检索学者的 Google Scholar 主页
- `search.keywords`: 目标论文标题关键词
- `search.keyword_operator`: `and` 或 `or`
- `search.fellow_titles`: 需要识别的标准头衔名

### 同义写法配置

同义写法现在支持直接在 `config.toml` 里配置：

```toml
[search.fellow_title_variants]
"IEEE Fellow" = ["IEEE Fellow", "Fellow of IEEE", "IEEE PES Fellow"]
"Life Fellow" = ["Life Fellow", "IEEE Life Fellow", "Life Fellow of IEEE"]
```

含义是：

- 左边是标准头衔名，必须出现在 `search.fellow_titles` 中
- 右边是该头衔允许匹配的不同写法
- 代码会先按标准头衔分组，再用这些变体去匹配证据页正文

### 爬虫与并发配置

- `crawler.max_profile_pages`: 抓取 Scholar 主页的页数
- `crawler.max_citing_works_per_target`: 每篇目标论文最多检查多少篇引用文章；填 `0` 表示尽可能全量分页抓取
- `crawler.max_authors_per_citing_work`: 每篇引用文章最多检查多少位作者；默认优先检查最后作者，再检查第一作者
- `crawler.reset_session_every_citing_works`: 每处理多少篇引用文章重置一次搜索会话，降低搜索引擎限流影响
- `crawler.max_workers`: 多线程并发 worker 数
- `crawler.author_search_results`: 每个作者最多分析多少条搜索结果
- `crawler.request_delay_seconds`: 请求间隔，避免过快访问

## 结果判定说明

- 当前关键词匹配基于 Scholar 论文标题。
- 引用关系来自 OpenAlex，不直接解析 Google Scholar 引用页。
- Fellow 识别优先使用官方/机构页面，并要求页面文本与作者单位信息有重合，以降低同名误判。
- Wikipedia、ResearchGate、LinkedIn 等弱证据源默认不作为有效命中依据。
- 如果 Google Scholar 返回限流，可在 `search.target_author_name` 中补充作者姓名，走 OpenAlex 作者论文回退路径。

## 代码结构

- `main.py`: 极薄入口
- `fellowfinder/cli.py`: CLI 参数与启动逻辑
- `fellowfinder/config.py`: 配置解析
- `fellowfinder/finder.py`: 主抓取流程、并发执行、检索逻辑
- `fellowfinder/matching.py`: 头衔匹配、同义写法扩展、证据规则
- `fellowfinder/models.py`: 数据模型
- `fellowfinder/output.py`: JSON/CSV 输出
- `fellowfinder/utils.py`: 通用文本与辅助函数
