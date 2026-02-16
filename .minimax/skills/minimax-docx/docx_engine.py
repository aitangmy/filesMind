#!/usr/bin/env python3
"""
OpenXML Document Build System

Central command-line interface for document compilation and validation.

Usage:
    python docx_engine.py {doctor|render|audit|preview|order} [options]

Design goals:
- Unified entry point for all document operations
- Automatic runtime detection with fallback provisioning
- Self-contained module path resolution
- Mandatory post-generation verification
"""

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Tuple

SCRIPT_LOCATION = Path(__file__).parent.resolve()

sys.path.insert(0, str(SCRIPT_LOCATION))
from diagnostics.compiler import CompilerDiagnostics


def resolve_project_home() -> Path:
    """Identify the active workspace directory.

    Returns the user's working directory or PROJECT_HOME environment variable.
    Build artifacts and outputs are placed here. Raises an error if this
    would resolve to the skill installation directory.
    """
    env_path = os.environ.get("PROJECT_HOME")
    home = Path(env_path) if env_path else Path.cwd()
    if home.resolve() == SCRIPT_LOCATION.resolve():
        raise RuntimeError(
            f"project_home resolved to the skill directory ({SCRIPT_LOCATION}). "
            "Run docx_engine.py from the user's working directory or set PROJECT_HOME."
        )
    return home


def resolve_staging_area() -> Path:
    """Return the path for intermediate build files."""
    return resolve_project_home() / ".docx_workspace"


def resolve_artifact_dir() -> Path:
    """Return the path for final document outputs."""
    return resolve_project_home() / "output"


def locate_dotnet_binary() -> Optional[Path]:
    """Scan common installation paths for the dotnet executable."""
    os_type = platform.system()
    search_paths = ["dotnet"]

    if os_type == "Windows":
        search_paths.extend([
            Path.home() / ".dotnet" / "dotnet.exe",
            Path(os.environ.get("ProgramFiles", "")) / "dotnet" / "dotnet.exe",
            Path(os.environ.get("ProgramFiles(x86)", "")) / "dotnet" / "dotnet.exe",
        ])
    else:
        search_paths.extend([
            Path.home() / ".dotnet" / "dotnet",
            Path("/usr/local/share/dotnet/dotnet"),
            Path("/usr/share/dotnet/dotnet"),
            Path("/opt/dotnet/dotnet"),
        ])

    for candidate in search_paths:
        if isinstance(candidate, str):
            found = shutil.which(candidate)
            if found:
                return Path(found)
        elif candidate.exists() and candidate.is_file():
            return candidate
    return None


def assess_runtime_health() -> Tuple[str, Optional[Path], Optional[str]]:
    """Check the state of the dotnet installation.

    Returns:
        Tuple of (status, binary_path, version_string) where status is one of:
        'ready', 'outdated', 'corrupted', or 'absent'
    """
    binary = locate_dotnet_binary()
    if not binary:
        return ("absent", None, None)

    try:
        proc = subprocess.run(
            [str(binary), "--version"],
            capture_output=True, text=True, timeout=10
        )
        if proc.returncode == 0:
            ver = proc.stdout.strip()
            try:
                major_ver = int(ver.split(".")[0])
                return ("ready", binary, ver) if major_ver >= 6 else ("outdated", binary, ver)
            except (ValueError, IndexError):
                return ("corrupted", binary, None)
        return ("corrupted", binary, None)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ("corrupted", binary, None)


def provision_dotnet() -> Optional[Path]:
    """Download and install .NET SDK automatically.

    Returns:
        Path to the installed binary, or None on failure.
    """
    os_type = platform.system()
    print("  Acquiring .NET SDK...")

    try:
        if os_type == "Windows":
            installer_url = "https://dot.net/v1/dotnet-install.ps1"
            target_dir = Path.home() / ".dotnet"

            powershell_script = f"""
            $ErrorActionPreference = 'Stop'
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $installer = Invoke-WebRequest -Uri '{installer_url}' -UseBasicParsing
            $execution = [scriptblock]::Create($installer.Content)
            & $execution -Channel 8.0 -InstallDir '{target_dir}'
            """
            subprocess.run(
                ["powershell", "-Command", powershell_script],
                capture_output=True, text=True, timeout=300
            )
            binary = target_dir / "dotnet.exe"
        else:
            installer_url = "https://dot.net/v1/dotnet-install.sh"
            target_dir = Path.home() / ".dotnet"

            installer_path = Path(tempfile.gettempdir()) / "dotnet-bootstrap.sh"
            subprocess.run(
                ["curl", "-sSL", installer_url, "-o", str(installer_path)],
                check=True, timeout=60
            )
            installer_path.chmod(0o755)
            subprocess.run(
                [str(installer_path), "--channel", "8.0", "--install-dir", str(target_dir)],
                check=True, timeout=300
            )
            binary = target_dir / "dotnet"

        if binary.exists():
            verify = subprocess.run([str(binary), "--version"], capture_output=True, text=True)
            if verify.returncode == 0:
                print(f"  + Provisioned: {verify.stdout.strip()}")
                return binary

        print("  - Provisioning unsuccessful")
        print("    Reference: https://dotnet.microsoft.com/download")
        return None

    except Exception as exc:
        print(f"  - Provisioning failed: {exc}")
        print("    Reference: https://dotnet.microsoft.com/download")
        return None


def guarantee_dotnet() -> Path:
    """Ensure dotnet is available, installing if needed.

    Exits the process if installation fails.
    """
    status, binary, ver = assess_runtime_health()

    if status == "ready":
        return binary
    elif status == "outdated":
        print(f"! Runtime {ver} is outdated (requires 6+), upgrading...")
        result = provision_dotnet()
        if result:
            return result
        sys.exit(1)
    elif status == "corrupted":
        print("! Runtime installation corrupted, reinstalling...")
        dotnet_home = Path.home() / ".dotnet"
        if dotnet_home.exists():
            shutil.rmtree(dotnet_home, ignore_errors=True)
        result = provision_dotnet()
        if result:
            return result
        sys.exit(1)
    else:
        print("o Runtime not detected, installing...")
        result = provision_dotnet()
        if result:
            return result
        sys.exit(1)


def audit_python_dependencies() -> dict:
    """Check availability of optional Python packages."""
    inventory = {}

    try:
        import lxml
        inventory["lxml"] = ("available", getattr(lxml, "__version__", "?"))
    except ImportError:
        inventory["lxml"] = ("optional", None)

    pandoc_binary = shutil.which("pandoc")
    if pandoc_binary:
        try:
            proc = subprocess.run(["pandoc", "--version"], capture_output=True, text=True, timeout=5)
            ver = proc.stdout.split("\n")[0].split()[-1] if proc.returncode == 0 else "?"
            inventory["pandoc"] = ("available", ver)
        except Exception:
            inventory["pandoc"] = ("available", "?")
    else:
        inventory["pandoc"] = ("optional", None)

    for pkg in ["playwright", "matplotlib", "PIL"]:
        try:
            __import__(pkg if pkg != "PIL" else "PIL.Image")
            inventory[pkg] = ("available", None)
        except ImportError:
            inventory[pkg] = ("optional", None)

    return inventory


def prepare_workspace():
    """Ensure workspace output directories exist."""
    staging = resolve_staging_area()
    output = resolve_artifact_dir()

    staging.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)


def execute_verification(document_path: Path, runtime: Path) -> bool:
    """Run the complete verification pipeline on a generated document."""
    from check.pipeline import ValidationPipeline
    from check.report import Gravity

    try:
        report = ValidationPipeline.standard().run(document_path)
        for issue in report.issues:
            prefix = {
                Gravity.BLOCKER: "!!",
                Gravity.WARNING: " !",
                Gravity.HINT: "  ",
            }.get(issue.gravity, "  ")
            print(f"  {prefix} [{issue.gravity.value}] {issue.location}: {issue.summary}")
        if report.has_blockers():
            return False
    except Exception as exc:
        print(f"Verification exception: {exc}")
        return False

    validator_dll = SCRIPT_LOCATION / "validator" / "DocxChecker.dll"
    if validator_dll.exists():
        try:
            proc = subprocess.run(
                [str(runtime), "--roll-forward", "LatestMajor", str(validator_dll), str(document_path)],
                capture_output=True, text=True
            )
            print(proc.stdout, end="")
            if proc.stderr:
                print(proc.stderr, end="", file=sys.stderr)
            if proc.returncode != 0:
                return False
        except Exception as exc:
            print(f"Schema validation exception: {exc}")
            return False

    return True


def extract_document_metrics(document_path: Path) -> dict:
    """Collect statistics about the document using pandoc."""
    metrics = {"characters": 0, "tokens": 0, "media_count": 0, "has_markup": False, "has_annotations": False}

    if not shutil.which("pandoc"):
        return metrics

    try:
        proc = subprocess.run(
            ["pandoc", str(document_path), "-t", "plain"],
            capture_output=True, text=True, timeout=30
        )
        if proc.returncode == 0:
            content = proc.stdout
            metrics["characters"] = len(content)
            metrics["tokens"] = len(content.split())

        with zipfile.ZipFile(document_path, 'r') as archive:
            entries = archive.namelist()
            metrics["media_count"] = sum(1 for e in entries if e.startswith("word/media/"))
            metrics["has_annotations"] = "word/comments.xml" in entries

            if "word/document.xml" in entries:
                doc_xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
                metrics["has_markup"] = "<w:ins" in doc_xml or "<w:del" in doc_xml
    except (subprocess.SubprocessError, zipfile.BadZipFile, OSError, UnicodeDecodeError):
        return metrics

    return metrics


def action_doctor():
    """Run environment diagnostics and automatic setup."""
    print("=== Environment Diagnostics ===")
    print()

    print("Paths:")
    print(f"  Skill root:    {SCRIPT_LOCATION}")
    print(f"  Project home:  {resolve_project_home()}")
    print(f"  Workspace:     {resolve_staging_area()}")
    print(f"  Output dir:    {resolve_artifact_dir()}")
    print()

    print("Runtime:")
    status, binary, ver = assess_runtime_health()
    status_map = {"ready": "+", "outdated": "!", "corrupted": "-", "absent": "o"}
    print(f"  {status_map[status]} dotnet {ver or status}")
    print(f"  + python {platform.python_version()}")

    deps = audit_python_dependencies()
    for name, (state, ver) in deps.items():
        icon = "+" if state == "available" else ("o" if state == "optional" else "-")
        ver_str = f" {ver}" if ver else ""
        suffix = " (required)" if state == "missing" else (" (optional)" if state == "optional" else "")
        print(f"  {icon} {name}{ver_str}{suffix}")
    print()

    needs_setup = status != "ready"

    if needs_setup:
        print("=== Provisioning Dependencies ===")
        runtime = guarantee_dotnet()
        ver_proc = subprocess.run([str(runtime), '--version'], capture_output=True, text=True)
        print(f"  + dotnet {ver_proc.stdout.strip()}")

        print()
        print("=== Preparing Workspace ===")
        prepare_workspace()
        print(f"  + {resolve_staging_area()}")
    else:
        staging = resolve_staging_area()
        if not staging.exists():
            print("=== Preparing Workspace ===")
            prepare_workspace()
            print(f"  + {staging}")
        else:
            print("Workspace:")
            print(f"  + {staging}")
            print(f"  + project {SCRIPT_LOCATION / 'src' / 'DocForge.csproj'}")

    print()
    print("Ready!")
    print(f"  Render: python {Path(__file__).name} render")
    print(f"  Preset: python {Path(__file__).name} render output.docx tech")
    print(f"  Template: dotnet run --project \"{SCRIPT_LOCATION / 'src' / 'DocForge.csproj'}\" -- from-template template.docx output.docx")
    print(f"  Output: {resolve_artifact_dir()}/")


def action_render(target_name: Optional[str] = None, preset: str = "tech"):
    """Compile source and generate a validated document from a preset template."""
    preset = preset.lower()
    if preset not in {"tech", "academic"}:
        print(f"- Unsupported preset: {preset}")
        print("  Available presets: tech, academic")
        sys.exit(1)

    runtime = guarantee_dotnet()
    prepare_workspace()

    output_dir = resolve_artifact_dir()

    if target_name:
        target = Path(target_name)
        if not target.is_absolute():
            target = output_dir / target_name
    else:
        target = output_dir / "document.docx"

    target.parent.mkdir(parents=True, exist_ok=True)

    print(">> Compiling...")
    proj_file = SCRIPT_LOCATION / "src" / "DocForge.csproj"
    proc = subprocess.run(
        [str(runtime), "build", str(proj_file), "--verbosity", "quiet"],
        capture_output=True, text=True, cwd=str(SCRIPT_LOCATION)
    )

    if proc.returncode != 0:
        print("!! Compilation failed")
        print()
        diagnostics = CompilerDiagnostics()
        full_output = proc.stdout + proc.stderr
        for line in full_output.split("\n"):
            if "error CS" in line:
                print(f"  {line}")
                suggestions = diagnostics.analyze(line)
                for suggestion in suggestions:
                    print(f"    > Hint: {suggestion.message}")
        sys.exit(1)
    print("  + Compiled")

    print(">> Generating...")
    run_env = os.environ.copy()
    run_env.setdefault("DOTNET_ROLL_FORWARD", "LatestMajor")
    proc = subprocess.run(
        [
            str(runtime),
            "run",
            "--project",
            str(proj_file),
            "--no-build",
            "--",
            preset,
            str(target),
            str(resolve_artifact_dir()),
        ],
        capture_output=True,
        text=True,
        cwd=str(SCRIPT_LOCATION),
        env=run_env,
    )

    if proc.returncode != 0:
        print("!! Generation failed")
        if proc.stdout:
            print(proc.stdout)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        sys.exit(1)

    if not target.exists():
        print(f"!! Output missing: {target}")
        print("  Verify preset run arguments and project mode")
        sys.exit(1)
    print("  + Generated")

    print(">> Verifying...")
    if not execute_verification(target, runtime):
        print()
        print("!! VERIFICATION FAILED - Document saved but may be invalid")
        print("-" * 58)
        print(f"Document: {target}")
        print("The file may not render correctly in Word/WPS.")
        print()
        print("Potential causes:")
        print("  * Editing existing document: source may be non-conformant")
        print("  * Creating new document: review error messages above")
        print("-" * 58)
        sys.exit(1)

    metrics = extract_document_metrics(target)
    if metrics["characters"] > 0:
        media_note = "" if metrics["media_count"] > 0 else " - verify image embedding path"
        print(f"  >> {metrics['characters']} chars, {metrics['tokens']} words, {metrics['media_count']} images{media_note}")
        print(f"  >> Structural check passed. Content review: pandoc \"{target}\" -t plain")
        if metrics["has_markup"] or metrics["has_annotations"]:
            print("     Track changes detected - use --track-changes=all for review")

    print()
    print(f"+ Complete: {target}")


def action_audit(document_path: str):
    """Validate an existing document file."""
    runtime = guarantee_dotnet()

    path = Path(document_path)
    if not path.exists():
        print(f"- Not found: {path}")
        sys.exit(1)

    print(f">> Auditing: {path}")
    if execute_verification(path, runtime):
        print("+ Valid")
    else:
        sys.exit(1)


def action_preview(document_path: str):
    """Display document text content using pandoc."""
    path = Path(document_path)
    if not path.exists():
        print(f"- Not found: {path}")
        sys.exit(1)

    if not shutil.which("pandoc"):
        print("- pandoc not installed")
        print("  Install: brew install pandoc (macOS) or apt install pandoc (Linux)")
        sys.exit(1)

    print(f">> Preview: {path}")
    print("-" * 60)
    proc = subprocess.run(
        ["pandoc", str(path), "-t", "plain"],
        capture_output=True, text=True, timeout=30
    )
    if proc.returncode == 0:
        print(proc.stdout)
    else:
        print(f"- Preview failed: {proc.stderr}")
        sys.exit(1)


def action_order(container_name: Optional[str] = None, profile: str = "repair"):
    """Inspect layered assembly order for OOXML containers."""
    from spec.ooxml_order import (
        build_container_orders,
        explain_container,
        get_phase_plan,
        known_profiles,
    )

    profiles = known_profiles()
    if container_name in profiles and profile == "repair":
        profile = container_name
        container_name = None

    if profile not in profiles:
        print(f"- Unknown order profile: {profile}")
        print(f"  Available profiles: {', '.join(profiles)}")
        sys.exit(1)

    orders = build_container_orders(profile)
    if not container_name:
        print("Known containers:")
        for name in sorted(orders):
            print(f"  - {explain_container(name, profile=profile)}")
        return

    sequence = orders.get(container_name)
    if sequence is None:
        print(f"- Unknown container: {container_name}")
        print(f"  Available: {', '.join(sorted(orders))}")
        sys.exit(1)

    print(explain_container(container_name, profile=profile))
    phases = get_phase_plan(container_name, profile=profile) or ()
    for phase in phases:
        joined = ", ".join(phase.elements)
        print(f"  [{phase.level}:{phase.name}] {joined}")
    print("  [flattened]")
    for idx, elem in enumerate(sequence, start=1):
        print(f"    {idx:>2}. {elem}")


def show_usage():
    """Print command reference."""
    staging = resolve_staging_area()
    output = resolve_artifact_dir()

    usage = f"""
Usage: python docx_engine.py <command> [options]

IMPORTANT: Run from the user's working directory, not the skill directory.
  .docx_workspace/ and output/ are created under cwd.

Commands:
  doctor          Environment diagnostics and auto-setup
  render [name] [preset]   Build, execute, validate preset document (default preset: tech)
  audit FILE      Validate existing document
  preview FILE    Quick content preview (requires pandoc)
  order [name] [profile]  Show OOXML layered order (profiles: minimal/repair/compat/strict)

Paths:
  Skill:     {SCRIPT_LOCATION}
  Workspace: {staging}
  Output:    {output}  (final deliverables)

Creation Workflow:
  1. python docx_engine.py doctor
  2. python docx_engine.py render report.docx tech

Modification Workflow:
  1. Analyze requirements
  2. python docx_engine.py render modified.docx academic

Template-Driven Workflow (when user provides a template):
  1. Keep the template as source of truth (no preset structure injection)
  2. Run: dotnet run --project "{SCRIPT_LOCATION / 'src' / 'DocForge.csproj'}" -- from-template template.docx output.docx
  3. Run: python docx_engine.py audit output.docx
"""
    print(usage.strip())


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        show_usage()
        sys.exit(0)

    command = sys.argv[1]

    if command == "doctor":
        action_doctor()
    elif command == "render":
        target = sys.argv[2] if len(sys.argv) > 2 else None
        preset = sys.argv[3] if len(sys.argv) > 3 else "tech"
        action_render(target, preset)
    elif command == "audit":
        if len(sys.argv) < 3:
            print("Usage: python docx_engine.py audit <document.docx>")
            sys.exit(1)
        action_audit(sys.argv[2])
    elif command == "preview":
        if len(sys.argv) < 3:
            print("Usage: python docx_engine.py preview <document.docx>")
            sys.exit(1)
        action_preview(sys.argv[2])
    elif command == "order":
        action_order(
            container_name=sys.argv[2] if len(sys.argv) > 2 else None,
            profile=sys.argv[3] if len(sys.argv) > 3 else "repair",
        )
    else:
        print(f"Unknown command: {command}")
        print("Run 'python docx_engine.py help' for reference")
        sys.exit(1)


if __name__ == "__main__":
    main()
