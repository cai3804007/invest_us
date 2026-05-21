#!/usr/bin/env python3

import sys
from rich.console import Console
from fetcher import MarketDataFetcher
from analyzer import MarketAnalyzer
from display import Dashboard, MarkdownReport
from news import NewsFetcher
from ai_summary import generate_ai_summary
from notifier import push_to_serverchan


def main():
    is_markdown = "--markdown" in sys.argv or "--md" in sys.argv
    no_push = "--no-push" in sys.argv

    if "--help" in sys.argv or "-h" in sys.argv:
        console = Console()
        console.print("[bold]美股市场监控工具[/]")
        console.print("用法: python main.py [选项]")
        console.print()
        console.print("选项:")
        console.print("  --markdown, --md   输出 Markdown 格式（用于 GitHub Actions）")
        console.print("  --no-push          禁用 Server酱推送")
        console.print("  --help, -h         显示帮助")
        console.print()
        console.print("环境变量 (Secrets):")
        console.print("  FRED_API_KEY          FRED 经济数据 (推荐)")
        console.print("  GEMINI_API_KEY        Google Gemini AI 智能分析")
        console.print("  SERPAPI_API_KEYS      SerpAPI 实时新闻搜索")
        console.print("  TAVILY_API_KEYS       Tavily 搜索 API")
        console.print("  SERVERCHAN3_SENDKEY   Server酱 手机推送")
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

        # 4. AI summary
        ai_text = generate_ai_summary(result, news_headlines=news_text, console=console)

        # 5. Output
        if is_markdown:
            report = MarkdownReport(result, news_articles=news_articles, ai_summary=ai_text)
            md_content = report.render()
            print(md_content)

            # 6. Push notification
            if not no_push:
                score = result["risk_score"]
                level = result["risk_level"]
                rec = result["recommendation"]
                title = f"📊 美股监控 | 风险{score} {level} | {rec}"
                push_to_serverchan(title, md_content, console=console)
        else:
            dashboard = Dashboard(result)
            dashboard.render()

            if ai_text:
                console.print()
                from rich.panel import Panel
                console.print(Panel(ai_text, title="[bold]🤖 AI 智能研判（已结合实时新闻）[/]", border_style="magenta"))

            # Push in terminal mode too (unless --no-push)
            if not no_push:
                report = MarkdownReport(result, news_articles=news_articles, ai_summary=ai_text)
                md_content = report.render()
                score = result["risk_score"]
                level = result["risk_level"]
                rec = result["recommendation"]
                title = f"📊 美股监控 | 风险{score} {level} | {rec}"
                push_to_serverchan(title, md_content, console=console)

    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
    except Exception as e:
        print(f"\n错误: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
