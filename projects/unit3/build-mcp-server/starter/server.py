#!/usr/bin/env python3
"""
Module 1: Basic MCP Server - Starter Code
"""

#this is the comment to check changes in git repository

import json
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Initialize the FastMCP server
mcp = FastMCP("pr-agent")

# PR template directory (shared across all modules)
TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"


# TODO: Implement tool functions here
# Example structure for a tool:
# @mcp.tool()
# async def analyze_file_changes(base_branch: str = "main", include_diff: bool = True) -> str:
#     """Get the full diff and list of changed files in the current git repository.
#     
#     Args:
#         base_branch: Base branch to compare against (default: main)
#         include_diff: Include the full diff content (default: true)
#     """
#     # Your implementation here
#     pass

# Minimal stub implementations so the server runs
# TODO: Replace these with your actual implementations

@mcp.tool()
async def analyze_file_changes(base_branch: str = "main", include_diff: bool = True, max_diff_lines: int = 500) -> str:
    """Get the full diff and list of changed files in the current git repository.
    
    Args:
        base_branch: Base branch to compare against (default: main)
        include_diff: Include the full diff content (default: true)
        max_diff_lines: Maximum number of diff lines to include (default: 500)
    """
    try:
        # Get Claude's working directory from MCP context
        context = mcp.get_context()
        roots_result = await context.session.list_roots()
        if not roots_result.roots:
            return json.dumps({"error": "No workspace roots available"})
        
        working_dir = roots_result.roots[0].uri.path
        
        # Get list of changed files
        files_result = subprocess.run(
            ["git", "diff", "--name-only", f"{base_branch}...HEAD"],
            cwd=working_dir,
            capture_output=True,
            text=True
        )
        
        if files_result.returncode != 0:
            return json.dumps({
                "error": "Failed to get changed files",
                "details": files_result.stderr.strip()
            })
        
        changed_files = [f.strip() for f in files_result.stdout.split('\n') if f.strip()]
        
        # Get diff statistics
        stats_result = subprocess.run(
            ["git", "diff", "--stat", f"{base_branch}...HEAD"],
            cwd=working_dir,
            capture_output=True,
            text=True
        )
        
        stats = stats_result.stdout.strip() if stats_result.returncode == 0 else "Stats unavailable"
        
        result = {
            "changed_files": changed_files,
            "file_count": len(changed_files),
            "stats": stats,
            "base_branch": base_branch
        }
        
        # Include diff content if requested
        if include_diff:
            diff_result = subprocess.run(
                ["git", "diff", f"{base_branch}...HEAD"],
                cwd=working_dir,
                capture_output=True,
                text=True
            )
            
            if diff_result.returncode == 0:
                diff_lines = diff_result.stdout.split('\n')
                
                if len(diff_lines) > max_diff_lines:
                    truncated_diff = '\n'.join(diff_lines[:max_diff_lines])
                    result["diff"] = truncated_diff
                    result["diff_truncated"] = True
                    result["total_diff_lines"] = len(diff_lines)
                    result["truncation_message"] = f"Diff truncated to {max_diff_lines} lines (total: {len(diff_lines)} lines)"
                else:
                    result["diff"] = diff_result.stdout
                    result["diff_truncated"] = False
            else:
                result["diff_error"] = diff_result.stderr.strip()
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": "Unexpected error occurred",
            "details": str(e)
        })


@mcp.tool()
async def get_pr_templates() -> str:
    """List available PR templates with their content."""
    try:
        if not TEMPLATES_DIR.exists():
            return json.dumps({
                "templates": [],
                "template_count": 0,
                "message": f"Templates directory not found at {TEMPLATES_DIR}"
            })
        
        if not TEMPLATES_DIR.is_dir():
            return json.dumps({
                "error": f"Templates path exists but is not a directory: {TEMPLATES_DIR}"
            })
        
        templates = []
        
        # Read all template files (commonly .md files)
        for template_file in TEMPLATES_DIR.glob("*"):
            if template_file.is_file():
                try:
                    with open(template_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    templates.append({
                        "name": template_file.name,
                        "path": str(template_file.relative_to(TEMPLATES_DIR)),
                        "content": content,
                        "size": len(content)
                    })
                except Exception as e:
                    templates.append({
                        "name": template_file.name,
                        "path": str(template_file.relative_to(TEMPLATES_DIR)),
                        "error": f"Failed to read file: {str(e)}"
                    })
        
        # Sort templates by name for consistent ordering
        templates.sort(key=lambda x: x["name"])
        
        return json.dumps({
            "templates": templates,
            "template_count": len(templates),
            "templates_dir": str(TEMPLATES_DIR)
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": "Unexpected error occurred while reading templates",
            "details": str(e)
        })


@mcp.tool()
async def suggest_template(changes_summary: str, change_type: str) -> str:
    """Let Claude analyze the changes and suggest the most appropriate PR template.
    
    Args:
        changes_summary: Your analysis of what the changes do
        change_type: The type of change you've identified (bug, feature, docs, refactor, test, etc.)
    """
    try:
        # First, get available templates
        templates_response = await get_pr_templates()
        templates_data = json.loads(templates_response)
        
        if "error" in templates_data:
            return json.dumps({
                "error": "Could not load templates",
                "details": templates_data["error"]
            })
        
        available_templates = templates_data.get("templates", [])
        
        if not available_templates:
            return json.dumps({
                "suggestion": None,
                "message": "No templates available to suggest",
                "templates_dir": templates_data.get("templates_dir", str(TEMPLATES_DIR))
            })
        
        # Define mapping from change types to template patterns
        type_mappings = {
            "bug": ["bug", "fix", "hotfix", "patch"],
            "feature": ["feature", "enhancement", "new"],
            "docs": ["docs", "documentation", "readme"],
            "refactor": ["refactor", "cleanup", "improvement"],
            "test": ["test", "testing", "spec"],
            "chore": ["chore", "maintenance", "update"],
            "breaking": ["breaking", "major"],
            "security": ["security", "vulnerability", "cve"]
        }
        
        # Find matching templates based on change type
        matching_templates = []
        change_type_lower = change_type.lower()
        
        # Direct match or pattern match
        patterns_to_check = type_mappings.get(change_type_lower, [change_type_lower])
        
        for template in available_templates:
            template_name_lower = template["name"].lower()
            
            # Check if any pattern matches the template name
            for pattern in patterns_to_check:
                if pattern in template_name_lower:
                    matching_templates.append({
                        **template,
                        "match_reason": f"Template name contains '{pattern}' which matches change type '{change_type}'"
                    })
                    break
        
        # If no direct matches, look for generic templates
        if not matching_templates:
            for template in available_templates:
                template_name_lower = template["name"].lower()
                if any(generic in template_name_lower for generic in ["default", "general", "standard", "basic"]):
                    matching_templates.append({
                        **template,
                        "match_reason": f"Generic template suitable for '{change_type}' changes"
                    })
        
        # Rank templates by relevance (prefer exact matches)
        if matching_templates:
            # Sort by match quality (exact type matches first)
            matching_templates.sort(key=lambda t: (
                change_type_lower not in t["name"].lower(),  # Exact matches first
                t["name"]  # Then alphabetical
            ))
            
            best_match = matching_templates[0]
            
            return json.dumps({
                "suggested_template": {
                    "name": best_match["name"],
                    "path": best_match["path"],
                    "match_reason": best_match["match_reason"]
                },
                "change_type": change_type,
                "changes_summary": changes_summary,
                "all_matches": [
                    {
                        "name": t["name"],
                        "path": t["path"],
                        "match_reason": t["match_reason"]
                    }
                    for t in matching_templates
                ],
                "total_available_templates": len(available_templates)
            }, indent=2)
        else:
            # No matches found, suggest first available template
            fallback_template = available_templates[0]
            return json.dumps({
                "suggested_template": {
                    "name": fallback_template["name"],
                    "path": fallback_template["path"],
                    "match_reason": f"No specific template found for '{change_type}', using fallback template"
                },
                "change_type": change_type,
                "changes_summary": changes_summary,
                "all_matches": [],
                "total_available_templates": len(available_templates),
                "note": f"Consider creating a template specifically for '{change_type}' changes"
            }, indent=2)
            
    except Exception as e:
        return json.dumps({
            "error": "Unexpected error occurred while suggesting template",
            "details": str(e)
        })


if __name__ == "__main__":
    mcp.run()