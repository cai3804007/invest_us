#!/usr/bin/env python3

import sys
from rich.console import Console
from fetcher import MarketDataFetcher
from analyzer import MarketAnalyzer
from display import Dashboard, MarkdownReport
from news import NewsFetcher
from ai_summary import generate_ai_summary
from notifier import build_report_title, push_to_serverchan

HELP = """[bold]美股市场监控工具[/]
用法: python main.py [选项]

选项:
  --markdown, --md   输出 Markdown 格式（用于 GitHub Actions）
  --no-push          禁用 Server酱推送
  --help, -h         显示帮助

环境变量 (Secrets):
  FRED_API_KEY          FRED 经济数据 (推荐)
  GEMINI_API_KEY        Google Gemini AI 智能分析
  GEMINI_MODEL          Gemini 模型名 (默认 gemini-flash-latest)
  SERPAPI_API_KEYS      SerpAPI 实时新闻搜索
  TAVILY_API_KEYS       Tavily 搜索 API
  SERVERCHAN3_SENDKEY   Server酱 手机推送
  REPORT_TYPE_LABEL     推送标题前缀，如 日报 / 周期
  UP_COLOR_CONVENTION   涨跌配色: us=绿涨红跌(默认) / cn=红涨绿跌
"""


def main():
    is_markdown = "--markdown" in sys.argv or "--md" in sys.argv
    no_push = "--no-push" in sys.argv

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

        # 4. AI summary
        ai_text = generate_ai_summary(result, news_headlines=news_text, console=console)

        # 5. Output
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

        # 6. Push notification (same path for both output modes)
        if not no_push:
            push_to_serverchan(build_report_title(result), md_content, console=console)

    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
    except Exception as e:
        print(f"\n错误: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
