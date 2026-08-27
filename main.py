#!/usr/bin/env python3

import sys
from rich.console import Console
from fetcher import MarketDataFetcher
from analyzer import MarketAnalyzer
from display import Dashboard, MarkdownReport
from news import NewsFetcher
from ai_summary import generate_ai_summary
from notifier import build_report_title, push_to_serverchan
import alerts as alert_mod

HELP = """[bold]美股市场监控工具[/]
用法: python main.py [选项]

选项:
  --markdown, --md   输出 Markdown 格式（用于 GitHub Actions）
  --no-push          禁用推送（仍会更新 state.json）
  --force-push       无异常也推送（用于手动查看全量报告）
  --digest           摘要模式：无异常也推送（用于每周复盘）
  --dry-run          不写 state.json（试跑，不影响后续的状态对比）
  --help, -h         显示帮助

推送策略:
  默认只在**检测到异常**时推送，避免每日推送导致的通知疲劳。
  异常分三类：
    价格异动  连续下跌 / 单日大跌 / 回撤跌破档位
    状态变化  跌破MA200 / 风险等级跃升 / 周期切换 / 新增危险信号
    持续状态  VIX高位 / 萨姆触发 / 信用利差走阔（每 10 天最多重复一次）

环境变量 (Secrets):
  FRED_API_KEY          FRED 经济数据 (推荐)
  GEMINI_API_KEY        Google Gemini AI 智能分析
  GEMINI_MODEL          Gemini 模型名 (默认 gemini-flash-latest)
  SERPAPI_API_KEYS      SerpAPI 实时新闻搜索
  TAVILY_API_KEYS       Tavily 搜索 API
  SERVERCHAN3_SENDKEY   Server酱 手机推送
  REPORT_TYPE_LABEL     推送标题前缀，如 日报 / 周期
  UP_COLOR_CONVENTION   涨跌配色: us=绿涨红跌(默认) / cn=红涨绿跌
  STATE_FILE            状态文件路径 (默认 state.json)
"""


def main():
    is_markdown = "--markdown" in sys.argv or "--md" in sys.argv
    no_push = "--no-push" in sys.argv
    force_push = "--force-push" in sys.argv
    digest = "--digest" in sys.argv
    dry_run = "--dry-run" in sys.argv

    if "--help" in sys.argv or "-h" in sys.argv:
        Console().print(HELP)
        return

    try:
        console = Console(stderr=True) if is_markdown else Console()

        # 1. Fetch market data
        fetcher = MarketDataFetcher()
        fetcher.fetch_all(console=console)

        # 2. Fetch real-time news
        news_fetcher = NewsFetcher()
        news_articles = news_fetcher.fetch(console=console)
        news_text = news_fetcher.get_headlines_text()

        # 3. Analyze
        console.print("[bold cyan]正在分析数据...[/]")
        analyzer = MarketAnalyzer(fetcher)
        result = analyzer.analyze()

        health = result.get("data_health", {})
        if health.get("missing_critical"):
            console.print(f"[bold red]⚠️ 关键数据缺失: "
                          f"{', '.join(health['missing_critical'])} — 本次不给出操作建议[/]")

        # 4. Detect anomalies against the previous run
        prev_state = alert_mod.load_state()
        engine = alert_mod.AlertEngine(result, prev_state)
        fired = engine.run()
        result["alerts"] = fired

        if engine.first_run:
            console.print("[yellow]首次运行：无历史状态，本次跳过「状态变化」类判断[/]")

        if fired:
            console.print(f"[bold]检测到 {len(fired)} 项异常:[/]")
            for a in fired:
                colour = {"critical": "bold red", "warning": "yellow", "info": "cyan"}[a["level"]]
                detail = f" — {a['detail']}" if a["detail"] else ""
                console.print(f"  [{colour}]• {a['title']}{detail}[/]")
        else:
            console.print("[green]无异常[/]")

        push = alert_mod.should_push(fired, force=force_push, digest=digest)

        # 5. AI summary — skipped when nothing is being pushed, since the whole
        #    point of the gate is to not spend a request on a quiet day.
        want_ai = push or not is_markdown
        ai_text = (generate_ai_summary(result, news_headlines=news_text, console=console)
                   if want_ai else "")

        # 6. Output
        report = MarkdownReport(result, news_articles=news_articles, ai_summary=ai_text)

        if is_markdown:
            md_content = report.render()
            print(md_content)
        else:
            Dashboard(result).render()
            if ai_text:
                from rich.panel import Panel
                console.print()
                console.print(Panel(ai_text, title="[bold]🤖 AI 智能研判（已结合实时新闻）[/]",
                                    border_style="magenta"))
            md_content = report.render()

        # 7. Push only when an anomaly justifies it
        if no_push:
            console.print("[dim]--no-push: 跳过推送[/]")
        elif push:
            reason = ("强制推送" if force_push else
                      "摘要模式" if digest and not fired else
                      f"{len(fired)} 项异常")
            console.print(f"[dim]推送原因: {reason}[/]")
            push_to_serverchan(build_report_title(result, alerts=fired),
                               md_content, console=console)
        else:
            console.print("[green]无异常，未推送（--force-push 可强制推送）[/]")

        # 8. Persist state for the next run's comparison
        if dry_run:
            console.print("[dim]--dry-run: 未写入 state.json[/]")
        else:
            alert_mod.save_state(result, fired, prev=prev_state, engine=engine)

    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
    except Exception as e:
        print(f"\n错误: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
