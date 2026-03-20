# .\thesis\electronic-chatbot\apps\api\app\application\circuits\circuit_generation_logger.py

"""Circuit Generation Logger - Save circuit generation sessions for reproducibility.

This module provides logging and traceability for circuit generation,
saving prompts, specs, and outputs for debugging and audit purposes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from app.domains.circuits.entities import Circuit

logger = logging.getLogger(__name__)


class CircuitGenerationLogger:
    """Logs circuit generation sessions for reproducibility and debugging."""
    
    def __init__(self, exports_dir: Path = None):
        """Initialize logger with export directory.
        
        Args:
            exports_dir: Directory to save session logs. Defaults to artifacts/exports/sessions
        """
        if exports_dir is None:
            exports_dir = Path("artifacts/exports/sessions")
        
        self.exports_dir = exports_dir
        self.exports_dir.mkdir(parents=True, exist_ok=True)
    
    def log_info(self, session_id: str, message: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Log informational message for a session.
        
        Args:
            session_id: Session identifier
            message: Log message
            metadata: Additional metadata
        """
        logger.info(f"[{session_id}] {message}", extra={"metadata": metadata or {}})
    
    def log_warning(self, session_id: str, message: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Log warning message for a session.
        
        Args:
            session_id: Session identifier
            message: Warning message
            metadata: Additional metadata
        """
        logger.warning(f"[{session_id}] {message}", extra={"metadata": metadata or {}})
    
    def log_error(
        self,
        session_id: str,
        error_type: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log error message for a session.
        
        Args:
            session_id: Session identifier
            error_type: Type of error
            message: Error message
            metadata: Additional metadata
        """
        logger.error(
            f"[{session_id}] {error_type}: {message}",
            extra={"metadata": metadata or {}},
            exc_info=metadata and metadata.get("traceback", False)
        )
    
    def log_generation_session(
        self,
        session_id: str,
        prompt: Optional[str],
        template_id: str,
        parameters: Dict[str, Any],
        circuit: Circuit,
        kicad_file_path: Optional[Path] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Path:
        """Log a complete circuit generation session.
        
        Args:
            session_id: Unique identifier for this session (usually circuit ID)
            prompt: User's original natural language prompt (if any)
            template_id: Template used for generation
            parameters: Template parameters used
            circuit: Generated Circuit entity
            kicad_file_path: Path to exported .kicad_sch file (if exported)
            metadata: Additional metadata to save
        
        Returns:
            Path to generated session log file
        """
        try:
            # Create session directory
            session_dir = self.exports_dir / session_id
            session_dir.mkdir(exist_ok=True)
            
            # Build session log
            session_log = {
                "session_id": session_id,
                "timestamp": datetime.now().isoformat(),
                "prompt": prompt,
                "template_id": template_id,
                "parameters": parameters,
                "circuit": {
                    "id": circuit.id,
                    "name": circuit.name,
                    "component_count": len(circuit.components),
                    "net_count": len(circuit.nets),
                    "port_count": len(circuit.ports),
                },
                "kicad_file": str(kicad_file_path) if kicad_file_path else None,
                "metadata": metadata or {}
            }
            
            # Save session log as JSON
            log_file = session_dir / "session.json"
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(session_log, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved generation session log: {log_file}")
            
            # If prompt exists, save it separately for easy review
            if prompt:
                prompt_file = session_dir / "prompt.txt"
                with open(prompt_file, "w", encoding="utf-8") as f:
                    f.write(prompt)
            
            # Save CircuitSpec as JSON (convert circuit to spec-like format)
            def comp_to_dict(comp):
                if hasattr(comp, "id"):
                    return {
                        "id": comp.id,
                        "type": getattr(comp, "type", None),
                        "params": getattr(comp, "parameters", None),
                    }
                return {"id": str(comp)}

            def net_to_dict(net):
                if hasattr(net, "id"):
                    return {
                        "id": net.id,
                        "nodes": getattr(net, "nodes", None),
                    }
                return {"id": str(net)}

            circuit_spec = {
                "id": getattr(circuit, "id", None),
                "name": getattr(circuit, "name", None),
                "template_id": template_id,
                "parameters": parameters,
                "components": [comp_to_dict(comp) for comp in getattr(circuit, "components", [])],
                "nets": [net_to_dict(net) for net in getattr(circuit, "nets", [])],
            }
            spec_file = session_dir / "circuit_spec.json"
            with open(spec_file, "w", encoding="utf-8") as f:
                json.dump(circuit_spec, f, indent=2, ensure_ascii=False)

            # Copy KiCad file to session directory if available
            if kicad_file_path and kicad_file_path.exists():
                dest_kicad = session_dir / f"{session_id}.kicad_sch"
                dest_kicad.write_text(kicad_file_path.read_text(encoding="utf-8"), encoding="utf-8")
            
        except Exception as e:
            logger.error(f"Failed to log generation session {session_id}: {e}", exc_info=True)
            # Don't fail the main operation if logging fails
            return None
    
    def _circuit_to_spec(
        self,
        circuit: Circuit,
        template_id: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Convert Circuit entity to CircuitSpec-like format for logging.
        
        Args:
            circuit: Circuit entity
            template_id: Template used
            parameters: Template parameters
        
        Returns:
            Dict in CircuitSpec format
        """
        spec = {
            "metadata": {
                "name": circuit.name,
                "description": f"Generated from {template_id}",
                "version": "1.0",
                "template_id": template_id,
                "parameters": parameters
            },
            "components": [],
            "nets": [],
            "ports": []
        }
        
        # Convert components
        for comp in circuit.components:
            comp_spec = {
                "id": comp.id,
                "type": comp.type.value,
                "value": comp.value,
                "pins": list(comp.pins)
            }
            spec["components"].append(comp_spec)
        
        # Convert nets
        for net in circuit.nets:
            net_spec = {
                "id": net.id,
                "pins": [{"component_id": p.component_id, "pin": p.pin} for p in net.pins]
            }
            spec["nets"].append(net_spec)
        
        # Convert ports
        for port in circuit.ports:
            port_spec = {
                "id": port.id,
                "direction": port.direction.value,
                "net_id": port.net_id
            }
            spec["ports"].append(port_spec)
        
        return spec
    
    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load a previously saved generation session.
        
        Args:
            session_id: Session identifier
        
        Returns:
            Session log dict or None if not found
        """
        try:
            session_dir = self.exports_dir / session_id
            log_file = session_dir / "session.json"
            
            if log_file.exists():
                with open(log_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            else:
                logger.warning(f"Session log not found: {session_id}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to load session {session_id}: {e}", exc_info=True)
            return None
    
    def list_sessions(self, limit: int = 50) -> list[Dict[str, Any]]:
        """List recent generation sessions.
        
        Args:
            limit: Maximum number of sessions to return
        
        Returns:
            List of session summaries (sorted by timestamp, newest first)
        """
        try:
            sessions = []
            
            # Find all session directories
            for session_dir in self.exports_dir.iterdir():
                if session_dir.is_dir():
                    log_file = session_dir / "session.json"
                    if log_file.exists():
                        try:
                            with open(log_file, "r", encoding="utf-8") as f:
                                session = json.load(f)
                                sessions.append({
                                    "session_id": session["session_id"],
                                    "timestamp": session["timestamp"],
                                    "template_id": session["template_id"],
                                    "has_prompt": session.get("prompt") is not None
                                })
                        except Exception as e:
                            logger.warning(f"Failed to read session {session_dir.name}: {e}")
            
            # Sort by timestamp (newest first)
            sessions.sort(key=lambda s: s["timestamp"], reverse=True)
            
            return sessions[:limit]
            
        except Exception as e:
            logger.error(f"Failed to list sessions: {e}", exc_info=True)
            return []
