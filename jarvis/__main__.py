#!/usr/bin/env python3
"""Jarvis - Personal AI Laptop Assistant"""
import sys
import argparse


def parse_args():
    parser = argparse.ArgumentParser(
        description="Jarvis - Tu asistente AI personal para la laptop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python -m jarvis                     # Modo interactivo
  python -m jarvis -q '¿cuánta RAM tengo?'  # Consulta rápida
  python -m jarvis --voice             # Con reconocimiento de voz
  python -m jarvis --clear             # Borrar historial
        """,
    )
    parser.add_argument("--voice", action="store_true", help="Activar reconocimiento de voz")
    parser.add_argument("--query", "-q", type=str, help="Ejecutar consulta única y salir")
    parser.add_argument("--clear", action="store_true", help="Borrar historial y salir")
    return parser.parse_args()


def main():
    args = parse_args()

    from .config import ANTHROPIC_API_KEY, JARVIS_NAME, VOICE_ENABLED
    from .brain.agent import JarvisAgent
    from .interface.cli import (
        print_banner,
        get_user_input,
        print_jarvis_response,
        print_thinking,
        print_error,
        print_info,
        console,
    )

    if not ANTHROPIC_API_KEY:
        print("[ERROR] ANTHROPIC_API_KEY no configurada.")
        print("  1. Copia jarvis/.env.example a jarvis/.env")
        print("  2. Edita jarvis/.env y agrega tu clave de API")
        print("  Obtén tu key en: https://console.anthropic.com/")
        sys.exit(1)

    agent = JarvisAgent()
    voice_on = args.voice or VOICE_ENABLED

    if args.clear:
        agent.history.clear()
        print_info("Historial borrado.")
        return

    if args.query:
        print_thinking(JARVIS_NAME)
        response = agent.chat(args.query)
        print_jarvis_response(response, JARVIS_NAME)
        if voice_on:
            from .interface.voice import speak
            speak(response)
        return

    print_banner(JARVIS_NAME)

    while True:
        try:
            if voice_on:
                from .interface.voice import listen
                text = listen()
                if text:
                    console.print(f"[bold cyan]Tú:[/bold cyan] {text}")
                else:
                    text = get_user_input()
            else:
                text = get_user_input()

            if not text or not text.strip():
                continue

            cmd = text.strip().lower()
            if cmd in ("salir", "exit", "quit", "q", "bye", "adios", "adiós"):
                print_info(f"{JARVIS_NAME} desconectado. Hasta luego.")
                break

            if cmd in ("limpiar", "clear", "/clear"):
                agent.history.clear()
                console.clear()
                print_banner(JARVIS_NAME)
                print_info("Historial borrado.")
                continue

            print_thinking(JARVIS_NAME)
            response = agent.chat(text)
            print_jarvis_response(response, JARVIS_NAME)

            if voice_on:
                from .interface.voice import speak
                speak(response)

        except KeyboardInterrupt:
            print_info(f"\n{JARVIS_NAME} interrumpido. Hasta luego.")
            break
        except Exception as e:
            print_error(f"Error inesperado: {e}")


if __name__ == "__main__":
    main()
