# .\\thesis\\electronic-chatbot\\apps\\api\\app\\infrastructure\\exporters\\kicad_cli_renderer.py
"""Công cụ render SVG từ KiCad CLI - Fallback generation.

Module này cung cấp server-side rendering của KiCad schematics / PCB layouts
thành SVG format bằng lệnh kicad-cli. Đây là fallback solution khi không thể
sử dụng KiCad API trực tiếp hoặc browser-side rendering.

Vietnamese:
- Trách nhiệm: Render sơ đồ/bản mạch KiCad thành SVG sử dụng CLI
- Quy trình: .kicad_sch/.kicad_pcb → kicad-cli → SVG output
- Yêu cầu: kicad-cli phải cài đặt trên server

English:
- Responsibility: Render KiCad schematics/PCB to SVG using CLI
- Workflow: .kicad_sch/.kicad_pcb → kicad-cli → SVG output
- Requirement: kicad-cli must be installed on server
"""

# ====== Lý do sử dụng thư viện ======
# asyncio: Async subprocess management cho kicad-cli async execution
# logging: Log CLI commands + errors
# os, shutil: File/directory operations
# subprocess: Execute kicad-cli commands
# pathlib: Path handling cho cross-platform compatibility
import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ====== KiCad CLI Rendering ======
class KiCadCLIRenderer:
    """Công cụ render sơ đồ/bản mạch KiCad thành SVG bằng kicad-cli.
    
    Class này gọi kicad-cli command line tool để render KiCad files
    (.kicad_sch, .kicad_pcb) thành SVG format cho web display.
    
    Responsibilities (Trách nhiệm):
    - Gọi kicad-cli để render .kicad_sch / .kicad_pcb
    - Quản lý temporary files cho rendering
    - Handle async subprocess execution
    """
    
    def __init__(self, kicad_cli_path: Optional[str] = None):
        """Initialize KiCad CLI renderer.
        
        Args:
            kicad_cli_path: Path to kicad-cli executable. If None, searches in PATH.
        """
        self.kicad_cli_path = kicad_cli_path or self._find_kicad_cli()
        if not self.kicad_cli_path:
            logger.warning("kicad-cli not found in PATH")
    
    def _find_kicad_cli(self) -> Optional[str]:
        """Find kicad-cli executable in system PATH or common locations.
        
        Returns:
            Path to kicad-cli executable or None if not found.
        """
        # Check if kicad-cli is in PATH
        if shutil.which("kicad-cli"):
            return "kicad-cli"
        
        # Common installation paths on Windows
        common_paths = [
            r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe",
            r"C:\Program Files\KiCad\7.0\bin\kicad-cli.exe",
            r"C:\Program Files (x86)\KiCad\8.0\bin\kicad-cli.exe",
            r"C:\Program Files (x86)\KiCad\7.0\bin\kicad-cli.exe",
        ]
        
        # Common installation paths on Linux/Mac
        if os.name != 'nt':
            common_paths.extend([
                "/usr/bin/kicad-cli",
                "/usr/local/bin/kicad-cli",
                "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
            ])
        
        for path in common_paths:
            if os.path.exists(path):
                return path
        
        return None
    
    def is_available(self) -> bool:
        """Check if kicad-cli is available.
        
        Returns:
            True if kicad-cli is found and executable.
        """
        return self.kicad_cli_path is not None
    
    async def render_to_svg(
        self,
        input_kicad_sch: Path,
        output_dir: Path,
        theme: str = "kicad_default"
    ) -> Optional[Path]:
        """Render a KiCad schematic to SVG.
        
        Args:
            input_kicad_sch: Path to input .kicad_sch file.
            output_dir: Directory where SVG will be saved.
            theme: Color theme for rendering (default: kicad_default).
        
        Returns:
            Path to generated SVG file or None if rendering failed.
        """
        if not self.is_available():
            logger.error("kicad-cli is not available")
            return None
        
        if not input_kicad_sch.exists():
            logger.error(f"Input file not found: {input_kicad_sch}")
            return None
        
        # Ensure output directory exists
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Expected output SVG path
        svg_filename = input_kicad_sch.stem + ".svg"
        output_svg = output_dir / svg_filename
        
        # Build kicad-cli command
        # Reference: https://docs.kicad.org/master/en/cli/cli.html
        cmd = [
            self.kicad_cli_path,
            "sch",
            "export",
            "svg",
            "--output", str(output_dir),
            "--theme", theme,
            str(input_kicad_sch)
        ]
        
        try:
            logger.info(f"Running kicad-cli: {' '.join(cmd)}")
            
            # Run command asynchronously
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                if output_svg.exists():
                    logger.info(f"SVG rendered successfully: {output_svg}")
                    return output_svg
                else:
                    logger.error(f"kicad-cli completed but SVG not found: {output_svg}")
                    logger.debug(f"stdout: {stdout.decode()}")
                    logger.debug(f"stderr: {stderr.decode()}")
                    return None
            else:
                logger.error(f"kicad-cli failed with code {process.returncode}")
                logger.error(f"stderr: {stderr.decode()}")
                return None
                
        except Exception as e:
            logger.error(f"Error running kicad-cli: {e}", exc_info=True)
            return None
    
    def render_to_svg_sync(
        self,
        input_kicad_sch: Path,
        output_dir: Path,
        theme: str = "kicad_default"
    ) -> Optional[Path]:
        """Synchronous version of render_to_svg.
        
        Args:
            input_kicad_sch: Path to input .kicad_sch file.
            output_dir: Directory where SVG will be saved.
            theme: Color theme for rendering (default: kicad_default).
        
        Returns:
            Path to generated SVG file or None if rendering failed.
        """
        if not self.is_available():
            logger.error("kicad-cli is not available")
            return None
        
        if not input_kicad_sch.exists():
            logger.error(f"Input file not found: {input_kicad_sch}")
            return None
        
        # Ensure output directory exists
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Expected output SVG path
        svg_filename = input_kicad_sch.stem + ".svg"
        output_svg = output_dir / svg_filename
        
        # Build kicad-cli command
        cmd = [
            self.kicad_cli_path,
            "sch",
            "export",
            "svg",
            "--output", str(output_dir),
            "--theme", theme,
            str(input_kicad_sch)
        ]
        
        try:
            logger.info(f"Running kicad-cli: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                if output_svg.exists():
                    logger.info(f"SVG rendered successfully: {output_svg}")
                    return output_svg
                else:
                    logger.error(f"kicad-cli completed but SVG not found: {output_svg}")
                    logger.debug(f"stdout: {result.stdout}")
                    logger.debug(f"stderr: {result.stderr}")
                    return None
            else:
                logger.error(f"kicad-cli failed with code {result.returncode}")
                logger.error(f"stderr: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.error("kicad-cli command timed out")
            return None
        except Exception as e:
            logger.error(f"Error running kicad-cli: {e}", exc_info=True)
            return None
