from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.markdown import Markdown
from rich import box

console = Console()


def print_banner(name: str = "Jarvis"):
    art = (
        f"[bold cyan]  J.A.R.V.I.S[/bold cyan]  [dim]v1.0[/dim]\n"
        f"  [dim]Just A Rather Very Intelligent System[/dim]\n\n"
        f"  [dim]Escribe [bold]salir[/bold] para terminar "
        f"| [bold]limpiar[/bold] para borrar historial[/dim]"
    )
    console.print()
    console.print(
        Panel(art, border_style="cyan", box=box.DOUBLE_EDGE, padding=(0, 2))
    )
    console.print()


def get_user_input() -> str:
    return Prompt.ask("[bold cyan]Tú[/bold cyan]")


def print_jarvis_response(text: str, name: str = "Jarvis"):
    console.print()
    console.print(
        Panel(
            Markdown(text),
            title=f"[bold green]{name}[/bold green]",
            border_style="green",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )
    console.print()


def print_thinking(name: str = "Jarvis"):
    console.print(f"[dim italic]{name} procesando...[/dim italic]")


def print_error(message: str):
    console.print(f"[bold red]✗ Error:[/bold red] {message}")


def print_info(message: str):
    console.print(f"[dim]{message}[/dim]")
