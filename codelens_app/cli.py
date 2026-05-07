import sys
from .pipeline import run_pipeline, load_state
from .query_engine import ask


def main():
    if len(sys.argv) < 2:
        _usage()
        return

    cmd = sys.argv[1]

    if cmd == "ingest":
        if len(sys.argv) < 3:
            print("Usage: python -m codelens_app.cli ingest <codebase_path>")
            return
        codebase_path = sys.argv[2]
        collection = run_pipeline(codebase_path)
        if collection:
            print(f"\nNow run: python -m codelens_app.cli ask \"your question\"")

    elif cmd == "ask":
        state = load_state()
        if not state:
            print("No codebase ingested yet. Run 'ingest' first.")
            return
        if len(sys.argv) < 3:
            print("Usage: python -m codelens_app.cli ask \"your question\"")
            return
        question = " ".join(sys.argv[2:])
        print(f"Question: {question}")
        print("=" * 60)
        ask(state["collection_name"], question)

    elif cmd == "status":
        state = load_state()
        if not state:
            print("No codebase ingested yet.")
            return
        print(f"Codebase path  : {state['codebase_path']}")
        print(f"Collection     : {state['collection_name']}")
        print(f"Files          : {state['file_count']}")
        print(f"Functions      : {state['function_count']}")
        print(f"Classes        : {state['class_count']}")

    else:
        _usage()


def _usage():
    print("CodeLens CLI")
    print()
    print("Commands:")
    print("  ingest <path>       Parse + embed a Python codebase")
    print("  ask \"question\"      Ask about the ingested codebase")
    print("  status              Show current codebase info")
    print()
    print("Examples:")
    print("  python -m codelens_app.cli ingest D:\\my-project")
    print("  python -m codelens_app.cli ask \"how does user auth work?\"")
    print("  python -m codelens_app.cli status")


if __name__ == "__main__":
    main()
