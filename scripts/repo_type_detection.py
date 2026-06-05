#!/usr/bin/env python3
"""repo_type_detection.py — Logik zur Erkennung des Repository-Typs und der dominanten Stacks.

Dieses Modul analysiert die Dateistruktur eines Repositories, um den Typ (z. B. docs-only, research, data, templates, configuration, project-management, oder code repository) und die dominante Technologie (z. B. Python, R, JavaScript) zu bestimmen.
"""

from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Dateiendungen und Muster zur Erkennung von Repository-Typen
CODE_FILE_EXTENSIONS = {
    # Programmiersprachen
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".java": "java",
    ".kt": "kotlin",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".swift": "swift",
    ".m": "objective-c",
    ".mm": "objective-c",
    ".sh": "shell",
    ".ps1": "powershell",
    ".r": "r",
    ".R": "r",
    ".pl": "perl",
    ".lua": "lua",
    ".scala": "scala",
    ".groovy": "groovy",
    ".dart": "dart",
    ".jl": "julia",
    ".f": "fortran",
    ".f90": "fortran",
    ".f95": "fortran",
    ".hs": "haskell",
    ".elm": "elm",
    ".clj": "clojure",
    ".erl": "erlang",
    ".ex": "elixir",
    ".exs": "elixir",
    ".fs": "fsharp",
    ".fsx": "fsharp",
    ".v": "vlang",
    ".zig": "zig",
    ".nim": "nim",
    ".cr": "crystal",
    ".d": "d",
    ".pas": "pascal",
    ".lisp": "lisp",
    ".scm": "scheme",
    ".ml": "ocaml",
    ".mli": "ocaml",
    ".vhdl": "vhdl",
    ".verilog": "verilog",
    ".sql": "sql",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".md": "markdown",
    ".rst": "rst",
    ".tex": "latex",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".xml": "xml",
    ".xsl": "xml",
    ".xslt": "xml",
    ".svg": "svg",
    ".csv": "csv",
    ".tsv": "tsv",
    ".xlsx": "excel",
    ".xls": "excel",
    ".ods": "ods",
    ".docx": "word",
    ".doc": "word",
    ".odt": "odt",
    ".pptx": "powerpoint",
    ".ppt": "powerpoint",
    ".odp": "odp",
    ".pdf": "pdf",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".gif": "image",
    ".bmp": "image",
    ".tiff": "image",
    ".webp": "image",
    ".mp3": "audio",
    ".wav": "audio",
    ".ogg": "audio",
    ".flac": "audio",
    ".mp4": "video",
    ".avi": "video",
    ".mkv": "video",
    ".mov": "video",
    ".wmv": "video",
    ".flv": "video",
    ".webm": "video",
    ".zip": "archive",
    ".tar": "archive",
    ".gz": "archive",
    ".7z": "archive",
    ".rar": "archive",
    ".xz": "archive",
    ".bz2": "archive",
    ".dll": "binary",
    ".exe": "binary",
    ".so": "binary",
    ".dylib": "binary",
    ".bin": "binary",
    ".dat": "binary",
    ".db": "database",
    ".sqlite": "database",
    ".sqlite3": "database",
    ".mdb": "database",
    ".accdb": "database",
    ".pkl": "pickle",
    ".pickle": "pickle",
    ".ipynb": "jupyter",
    ".lock": "lock",
    ".log": "log",
    ".gitignore": "git",
    ".dockerignore": "docker",
    "Dockerfile": "docker",
    "docker-compose.yml": "docker",
    "docker-compose.yaml": "docker",
    "compose.yml": "docker",
    "compose.yaml": "docker",
    "Makefile": "make",
    "CMakeLists.txt": "cmake",
    "package.json": "nodejs",
    "package-lock.json": "nodejs",
    "yarn.lock": "nodejs",
    "pnpm-lock.yaml": "nodejs",
    "npm-shrinkwrap.json": "nodejs",
    "tsconfig.json": "typescript",
    "webpack.config.js": "nodejs",
    "vite.config.ts": "nodejs",
    "rollup.config.js": "nodejs",
    "jest.config.js": "nodejs",
    "babel.config.js": "nodejs",
    "postcss.config.js": "nodejs",
    "tailwind.config.js": "nodejs",
    "next.config.js": "nodejs",
    "nuxt.config.js": "nodejs",
    "vue.config.js": "nodejs",
    "angular.json": "nodejs",
    "nx.json": "nodejs",
    "lerna.json": "nodejs",
    "turbo.json": "nodejs",
    "pnpm-workspace.yaml": "nodejs",
    "Gemfile": "ruby",
    "Gemfile.lock": "ruby",
    "Rakefile": "ruby",
    "requirements.txt": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "pyproject.toml": "python",
    "Pipfile": "python",
    "Pipfile.lock": "python",
    "poetry.lock": "python",
    "go.mod": "go",
    "go.sum": "go",
    "Cargo.toml": "rust",
    "Cargo.lock": "rust",
    "composer.json": "php",
    "composer.lock": "php",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "java",
    "settings.gradle": "java",
    "settings.gradle.kts": "java",
    "gradle.properties": "java",
    "gradle-wrapper.properties": "java",
    "build.sbt": "scala",
    "project/build.properties": "scala",
    "project/plugins.sbt": "scala",
    "pubspec.yaml": "dart",
    "pubspec.lock": "dart",
    "mix.exs": "elixir",
    "rebar.config": "erlang",
    "stack.yaml": "haskell",
    "cabal.config": "haskell",
    "*.cabal": "haskell",
    "project.clj": "clojure",
    "deps.edn": "clojure",
    "shadow-cljs.edn": "clojure",
    "build.boot": "clojure",
    "package.yaml": "haskell",
    "cabal.project": "haskell",
    "*.hs": "haskell",
    "*.lhs": "haskell",
    "*.sc": "scala",
    "*.scala": "scala",
    "*.java": "java",
    "*.kt": "kotlin",
    "*.kts": "kotlin",
    "*.groovy": "groovy",
    "*.gradle": "groovy",
    "*.gradle.kts": "kotlin",
    "*.php": "php",
    "*.inc": "php",
    "*.module": "php",
    "*.ctp": "php",
    "*.twig": "php",
    "*.cs": "csharp",
    "*.fs": "fsharp",
    "*.fsx": "fsharp",
    "*.fsi": "fsharp",
    "*.vb": "vbnet",
    "*.cpp": "cpp",
    "*.c": "c",
    "*.h": "c",
    "*.hpp": "cpp",
    "*.cc": "cpp",
    "*.cxx": "cpp",
    "*.hxx": "cpp",
    "*.m": "objective-c",
    "*.mm": "objective-c",
    "*.swift": "swift",
    "*.rb": "ruby",
    "*.gemspec": "ruby",
    "*.py": "python",
    "*.pyi": "python",
    "*.pyx": "python",
    "*.pxd": "python",
    "*.js": "javascript",
    "*.jsx": "javascript",
    "*.ts": "typescript",
    "*.tsx": "typescript",
    "*.vue": "vue",
    "*.svelte": "svelte",
    "*.html": "html",
    "*.htm": "html",
    "*.css": "css",
    "*.scss": "scss",
    "*.sass": "sass",
    "*.less": "less",
    "*.styl": "stylus",
    "*.json": "json",
    "*.yaml": "yaml",
    "*.yml": "yaml",
    "*.toml": "toml",
    "*.ini": "ini",
    "*.cfg": "ini",
    "*.conf": "ini",
    "*.md": "markdown",
    "*.rst": "rst",
    "*.tex": "latex",
    "*.bib": "latex",
    "*.xml": "xml",
    "*.xsl": "xml",
    "*.xslt": "xml",
    "*.svg": "svg",
    "*.csv": "csv",
    "*.tsv": "tsv",
    "*.xlsx": "excel",
    "*.xls": "excel",
    "*.ods": "ods",
    "*.docx": "word",
    "*.doc": "word",
    "*.odt": "odt",
    "*.pptx": "powerpoint",
    "*.ppt": "powerpoint",
    "*.odp": "odp",
    "*.pdf": "pdf",
    "*.jpg": "image",
    "*.jpeg": "image",
    "*.png": "image",
    "*.gif": "image",
    "*.bmp": "image",
    "*.tiff": "image",
    "*.webp": "image",
    "*.mp3": "audio",
    "*.wav": "audio",
    "*.ogg": "audio",
    "*.flac": "audio",
    "*.mp4": "video",
    "*.avi": "video",
    "*.mkv": "video",
    "*.mov": "video",
    "*.wmv": "video",
    "*.flv": "video",
    "*.webm": "video",
    "*.zip": "archive",
    "*.tar": "archive",
    "*.gz": "archive",
    "*.7z": "archive",
    "*.rar": "archive",
    "*.xz": "archive",
    "*.bz2": "archive",
    "*.dll": "binary",
    "*.exe": "binary",
    "*.so": "binary",
    "*.dylib": "binary",
    "*.bin": "binary",
    "*.dat": "binary",
    "*.db": "database",
    "*.sqlite": "database",
    "*.sqlite3": "database",
    "*.mdb": "database",
    "*.accdb": "database",
    "*.pkl": "pickle",
    "*.pickle": "pickle",
    "*.ipynb": "jupyter",
    "*.lock": "lock",
    "*.log": "log",
    "*.gitignore": "git",
    "*.dockerignore": "docker",
    "Dockerfile": "docker",
    "docker-compose.yml": "docker",
    "docker-compose.yaml": "docker",
    "compose.yml": "docker",
    "compose.yaml": "docker",
    "Makefile": "make",
    "CMakeLists.txt": "cmake",
    "package.json": "nodejs",
    "package-lock.json": "nodejs",
    "yarn.lock": "nodejs",
    "pnpm-lock.yaml": "nodejs",
    "npm-shrinkwrap.json": "nodejs",
    "tsconfig.json": "typescript",
    "webpack.config.js": "nodejs",
    "vite.config.ts": "nodejs",
    "rollup.config.js": "nodejs",
    "jest.config.js": "nodejs",
    "babel.config.js": "nodejs",
    "postcss.config.js": "nodejs",
    "tailwind.config.js": "nodejs",
    "next.config.js": "nodejs",
    "nuxt.config.js": "nodejs",
    "vue.config.js": "nodejs",
    "angular.json": "nodejs",
    "nx.json": "nodejs",
    "lerna.json": "nodejs",
    "turbo.json": "nodejs",
    "pnpm-workspace.yaml": "nodejs",
    "Gemfile": "ruby",
    "Gemfile.lock": "ruby",
    "Rakefile": "ruby",
    "requirements.txt": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "pyproject.toml": "python",
    "Pipfile": "python",
    "Pipfile.lock": "python",
    "poetry.lock": "python",
    "go.mod": "go",
    "go.sum": "go",
    "Cargo.toml": "rust",
    "Cargo.lock": "rust",
    "composer.json": "php",
    "composer.lock": "php",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "java",
    "settings.gradle": "java",
    "settings.gradle.kts": "java",
    "gradle.properties": "java",
    "gradle-wrapper.properties": "java",
    "build.sbt": "scala",
    "project/build.properties": "scala",
    "project/plugins.sbt": "scala",
    "pubspec.yaml": "dart",
    "pubspec.lock": "dart",
    "mix.exs": "elixir",
    "rebar.config": "erlang",
    "stack.yaml": "haskell",
    "cabal.config": "haskell",
    "*.cabal": "haskell",
    "project.clj": "clojure",
    "deps.edn": "clojure",
    "shadow-cljs.edn": "clojure",
    "build.boot": "clojure",
    "package.yaml": "haskell",
    "cabal.project": "haskell",
}

# Muster zur Erkennung von Repository-Typen
REPO_TYPE_PATTERNS = {
    "docs-only": {
        "description": "Ein Repository, das hauptsächlich Dokumentation enthält (z. B. Markdown, RST, LaTeX).",
        "file_patterns": {
            "*.md",
            "*.rst",
            "*.tex",
            "*.pdf",
            "README.md",
            "LICENSE",
            "LICENSE.md",
            "LICENSE.txt",
            "docs/",
            "documentation/",
        },
        "excluded_patterns": {
            "*.py",
            "*.js",
            "*.java",
            "*.go",
            "*.rs",
            "*.rb",
            "*.php",
            "*.cs",
            "*.cpp",
            "*.c",
            "*.h",
            "*.sh",
            "*.ps1",
            "*.r",
            "*.R",
            "*.pl",
            "*.lua",
            "*.scala",
            "*.swift",
            "*.kt",
            "*.m",
            "*.mm",
            "*.ts",
            "*.jsx",
            "*.tsx",
            "*.vue",
            "*.svelte",
            "*.html",
            "*.css",
            "*.scss",
            "*.sass",
            "*.less",
            "*.styl",
            "*.json",
            "*.yaml",
            "*.yml",
            "*.toml",
            "*.ini",
            "*.cfg",
            "*.conf",
            "*.xml",
            "*.xsl",
            "*.xslt",
            "*.svg",
            "*.csv",
            "*.tsv",
            "*.xlsx",
            "*.xls",
            "*.ods",
            "*.docx",
            "*.doc",
            "*.odt",
            "*.pptx",
            "*.ppt",
            "*.odp",
            "*.pdf",
            "*.jpg",
            "*.jpeg",
            "*.png",
            "*.gif",
            "*.bmp",
            "*.tiff",
            "*.webp",
            "*.mp3",
            "*.wav",
            "*.ogg",
            "*.flac",
            "*.mp4",
            "*.avi",
            "*.mkv",
            "*.mov",
            "*.wmv",
            "*.flv",
            "*.webm",
            "*.zip",
            "*.tar",
            "*.gz",
            "*.7z",
            "*.rar",
            "*.xz",
            "*.bz2",
            "*.dll",
            "*.exe",
            "*.so",
            "*.dylib",
            "*.bin",
            "*.dat",
            "*.db",
            "*.sqlite",
            "*.sqlite3",
            "*.mdb",
            "*.accdb",
            "*.pkl",
            "*.pickle",
            "*.ipynb",
            "*.lock",
            "*.log",
            "*.gitignore",
            "*.dockerignore",
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
            "Makefile",
            "CMakeLists.txt",
            "package.json",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "npm-shrinkwrap.json",
            "tsconfig.json",
            "webpack.config.js",
            "vite.config.ts",
            "rollup.config.js",
            "jest.config.js",
            "babel.config.js",
            "postcss.config.js",
            "tailwind.config.js",
            "next.config.js",
            "nuxt.config.js",
            "vue.config.js",
            "angular.json",
            "nx.json",
            "lerna.json",
            "turbo.json",
            "pnpm-workspace.yaml",
            "Gemfile",
            "Gemfile.lock",
            "Rakefile",
            "requirements.txt",
            "setup.py",
            "setup.cfg",
            "pyproject.toml",
            "Pipfile",
            "Pipfile.lock",
            "poetry.lock",
            "go.mod",
            "go.sum",
            "Cargo.toml",
            "Cargo.lock",
            "composer.json",
            "composer.lock",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "settings.gradle",
            "settings.gradle.kts",
            "gradle.properties",
            "gradle-wrapper.properties",
            "build.sbt",
            "project/build.properties",
            "project/plugins.sbt",
            "pubspec.yaml",
            "pubspec.lock",
            "mix.exs",
            "rebar.config",
            "stack.yaml",
            "cabal.config",
            "*.cabal",
            "project.clj",
            "deps.edn",
            "shadow-cljs.edn",
            "build.boot",
            "package.yaml",
            "cabal.project",
        },
    },
    "research": {
        "description": "Ein Repository, das Forschungsnotizen, Daten oder Analysen enthält (z. B. Jupyter-Notebooks, R-Skripte, Daten).",
        "file_patterns": {
            "*.ipynb",
            "*.R",
            "*.r",
            "*.py",
            "*.csv",
            "*.tsv",
            "*.xlsx",
            "*.xls",
            "*.ods",
            "*.json",
            "*.yaml",
            "*.yml",
            "*.md",
            "*.pdf",
            "data/",
            "notebooks/",
            "analysis/",
            "research/",
            "reports/",
        },
    },
    "data": {
        "description": "Ein Repository, das hauptsächlich Daten enthält (z. B. CSV, JSON, SQL-Dumps).",
        "file_patterns": {
            "*.csv",
            "*.tsv",
            "*.xlsx",
            "*.xls",
            "*.ods",
            "*.json",
            "*.yaml",
            "*.yml",
            "*.sql",
            "*.db",
            "*.sqlite",
            "*.sqlite3",
            "*.mdb",
            "*.accdb",
            "*.pkl",
            "*.pickle",
            "data/",
            "datasets/",
        },
    },
    "templates": {
        "description": "Ein Repository, das Vorlagen oder Boilerplate-Code enthält (z. B. Projekt-Templates, Code-Snippets).",
        "file_patterns": {
            "*.md",
            "*.txt",
            "*.json",
            "*.yaml",
            "*.yml",
            "*.toml",
            "*.ini",
            "*.cfg",
            "*.conf",
            "*.xml",
            "*.xsl",
            "*.xslt",
            "*.svg",
            "*.html",
            "*.css",
            "*.scss",
            "*.sass",
            "*.less",
            "*.styl",
            "*.js",
            "*.ts",
            "*.jsx",
            "*.tsx",
            "*.py",
            "*.java",
            "*.kt",
            "*.go",
            "*.rs",
            "*.rb",
            "*.php",
            "*.cs",
            "*.cpp",
            "*.c",
            "*.h",
            "*.sh",
            "*.ps1",
            "templates/",
            "boilerplate/",
            "snippets/",
        },
    },
    "configuration": {
        "description": "Ein Repository, das hauptsächlich Konfigurationsdateien enthält (z. B. Ansible, Terraform, Kubernetes).",
        "file_patterns": {
            "*.yaml",
            "*.yml",
            "*.json",
            "*.toml",
            "*.ini",
            "*.cfg",
            "*.conf",
            "*.tf",
            "*.tfvars",
            "*.hcl",
            "*.env",
            "*.env.example",
            "*.properties",
            "*.xml",
            "*.xsl",
            "*.xslt",
            "*.svg",
            "*.html",
            "*.css",
            "*.scss",
            "*.sass",
            "*.less",
            "*.styl",
            "*.sh",
            "*.ps1",
            "*.md",
            "config/",
            "configuration/",
            "ansible/",
            "terraform/",
            "kubernetes/",
            "k8s/",
        },
    },
    "project-management": {
        "description": "Ein Repository, das Projektmanagement-Dateien enthält (z. B. Aufgabenlisten, Roadmaps, Pläne).",
        "file_patterns": {
            "*.md",
            "*.txt",
            "*.json",
            "*.yaml",
            "*.yml",
            "*.toml",
            "*.ini",
            "*.cfg",
            "*.conf",
            "*.xml",
            "*.xsl",
            "*.xslt",
            "*.svg",
            "*.html",
            "*.css",
            "*.scss",
            "*.sass",
            "*.less",
            "*.styl",
            "*.sh",
            "*.ps1",
            "*.csv",
            "*.tsv",
            "*.xlsx",
            "*.xls",
            "*.ods",
            "*.docx",
            "*.doc",
            "*.odt",
            "*.pptx",
            "*.ppt",
            "*.odp",
            "*.pdf",
            "*.jpg",
            "*.jpeg",
            "*.png",
            "*.gif",
            "*.bmp",
            "*.tiff",
            "*.webp",
            "*.mp3",
            "*.wav",
            "*.ogg",
            "*.flac",
            "*.mp4",
            "*.avi",
            "*.mkv",
            "*.mov",
            "*.wmv",
            "*.flv",
            "*.webm",
            "*.zip",
            "*.tar",
            "*.gz",
            "*.7z",
            "*.rar",
            "*.xz",
            "*.bz2",
            "*.dll",
            "*.exe",
            "*.so",
            "*.dylib",
            "*.bin",
            "*.dat",
            "*.db",
            "*.sqlite",
            "*.sqlite3",
            "*.mdb",
            "*.accdb",
            "*.pkl",
            "*.pickle",
            "*.ipynb",
            "*.lock",
            "*.log",
            "*.gitignore",
            "*.dockerignore",
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
            "Makefile",
            "CMakeLists.txt",
            "package.json",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "npm-shrinkwrap.json",
            "tsconfig.json",
            "webpack.config.js",
            "vite.config.ts",
            "rollup.config.js",
            "jest.config.js",
            "babel.config.js",
            "postcss.config.js",
            "tailwind.config.js",
            "next.config.js",
            "nuxt.config.js",
            "vue.config.js",
            "angular.json",
            "nx.json",
            "lerna.json",
            "turbo.json",
            "pnpm-workspace.yaml",
            "Gemfile",
            "Gemfile.lock",
            "Rakefile",
            "requirements.txt",
            "setup.py",
            "setup.cfg",
            "pyproject.toml",
            "Pipfile",
            "Pipfile.lock",
            "poetry.lock",
            "go.mod",
            "go.sum",
            "Cargo.toml",
            "Cargo.lock",
            "composer.json",
            "composer.lock",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "settings.gradle",
            "settings.gradle.kts",
            "gradle.properties",
            "gradle-wrapper.properties",
            "build.sbt",
            "project/build.properties",
            "project/plugins.sbt",
            "pubspec.yaml",
            "pubspec.lock",
            "mix.exs",
            "rebar.config",
            "stack.yaml",
            "cabal.config",
            "*.cabal",
            "project.clj",
            "deps.edn",
            "shadow-cljs.edn",
            "build.boot",
            "package.yaml",
            "cabal.project",
            "planning/",
            "roadmap/",
            "tasks/",
            "project/",
            "management/",
        },
    },
    "code": {
        "description": "Ein Repository, das hauptsächlich Code enthält (z. B. Python, JavaScript, Java).",
        "file_patterns": {
            "*.py",
            "*.js",
            "*.ts",
            "*.java",
            "*.kt",
            "*.go",
            "*.rs",
            "*.rb",
            "*.php",
            "*.cs",
            "*.cpp",
            "*.c",
            "*.h",
            "*.sh",
            "*.ps1",
            "*.r",
            "*.R",
            "*.pl",
            "*.lua",
            "*.scala",
            "*.swift",
            "*.kt",
            "*.m",
            "*.mm",
            "*.tsx",
            "*.jsx",
            "*.vue",
            "*.svelte",
            "src/",
            "lib/",
            "app/",
            "scripts/",
            "tests/",
            "test/",
        },
    },
}

# Standard-Validierungskommandos für verschiedene Repository-Typen
DEFAULT_VALIDATION_COMMANDS = {
    "docs-only": {
        "description": "Validierungskommandos für Dokumentations-Repositories.",
        "commands": {
            "markdown-lint": "markdownlint **/*.md",
            "spell-check": "cspell **/*.md",
        },
    },
    "research": {
        "description": "Validierungskommandos für Forschungs-Repositories.",
        "commands": {
            "jupyter-nbconvert": "jupyter nbconvert --to notebook --inplace **/*.ipynb",
            "markdown-lint": "markdownlint **/*.md",
        },
    },
    "data": {
        "description": "Validierungskommandos für Daten-Repositories.",
        "commands": {
            "csv-lint": "csvlint **/*.csv",
            "json-lint": "jsonlint **/*.json",
        },
    },
    "templates": {
        "description": "Validierungskommandos für Template-Repositories.",
        "commands": {
            "markdown-lint": "markdownlint **/*.md",
        },
    },
    "configuration": {
        "description": "Validierungskommandos für Konfigurations-Repositories.",
        "commands": {
            "yaml-lint": "yamllint **/*.yaml **/*.yml",
            "json-lint": "jsonlint **/*.json",
        },
    },
    "project-management": {
        "description": "Validierungskommandos für Projektmanagement-Repositories.",
        "commands": {
            "markdown-lint": "markdownlint **/*.md",
        },
    },
    "code": {
        "description": "Validierungskommandos für Code-Repositories.",
        "commands": {
            "python": {
                "lint": "pylint **/*.py",
                "test": "python -m unittest discover -s tests",
            },
            "javascript": {
                "lint": "eslint **/*.js",
                "test": "npm test",
            },
            "java": {
                "lint": "checkstyle -c sun_checks.xml **/*.java",
                "test": "mvn test",
            },
            "go": {
                "lint": "golint ./...",
                "test": "go test ./...",
            },
            "rust": {
                "lint": "cargo clippy",
                "test": "cargo test",
            },
            "ruby": {
                "lint": "rubocop",
                "test": "rake test",
            },
            "php": {
                "lint": "phpcs",
                "test": "phpunit",
            },
            "csharp": {
                "lint": "dotnet format",
                "test": "dotnet test",
            },
            "cpp": {
                "lint": "cppcheck",
                "test": "ctest",
            },
            "c": {
                "lint": "cppcheck",
                "test": "ctest",
            },
            "shell": {
                "lint": "shellcheck **/*.sh",
            },
            "powershell": {
                "lint": "pwsh -Command Invoke-ScriptAnalyzer -Path **/*.ps1",
            },
            "r": {
                "lint": "lintr::lint_dir()",
            },
        },
    },
}

# Standard-Validierungskommandos für verschiedene Sprachen
LANGUAGE_VALIDATION_COMMANDS = {
    "python": {
        "lint": "pylint **/*.py",
        "test": "python -m unittest discover -s tests",
    },
    "javascript": {
        "lint": "eslint **/*.js",
        "test": "npm test",
    },
    "typescript": {
        "lint": "eslint **/*.ts",
        "test": "npm test",
    },
    "java": {
        "lint": "checkstyle -c sun_checks.xml **/*.java",
        "test": "mvn test",
    },
    "go": {
        "lint": "golint ./...",
        "test": "go test ./...",
    },
    "rust": {
        "lint": "cargo clippy",
        "test": "cargo test",
    },
    "ruby": {
        "lint": "rubocop",
        "test": "rake test",
    },
    "php": {
        "lint": "phpcs",
        "test": "phpunit",
    },
    "csharp": {
        "lint": "dotnet format",
        "test": "dotnet test",
    },
    "cpp": {
        "lint": "cppcheck",
        "test": "ctest",
    },
    "c": {
        "lint": "cppcheck",
        "test": "ctest",
    },
    "shell": {
        "lint": "shellcheck **/*.sh",
    },
    "powershell": {
        "lint": "pwsh -Command Invoke-ScriptAnalyzer -Path **/*.ps1",
    },
    "r": {
        "lint": "lintr::lint_dir()",
    },
}

@dataclass
class RepositoryType:
    """Repräsentiert den erkannten Repository-Typ und die dominante Technologie."""
    type: str
    description: str
    dominant_language: Optional[str]
    file_counts: Dict[str, int]
    validation_commands: Dict[str, str]


def detect_repository_type(repo_path: str) -> RepositoryType:
    """Erkennt den Repository-Typ und die dominante Technologie.
    
    Args:
        repo_path: Pfad zum Repository.
        
    Returns:
        RepositoryType: Objekt mit Informationen zum Repository-Typ.
    """
    file_counts = count_file_types(repo_path)
    repo_type = determine_repo_type(file_counts)
    dominant_language = determine_dominant_language(file_counts)
    validation_commands = get_validation_commands(repo_type, dominant_language)
    
    return RepositoryType(
        type=repo_type,
        description=REPO_TYPE_PATTERNS[repo_type]["description"],
        dominant_language=dominant_language,
        file_counts=file_counts,
        validation_commands=validation_commands,
    )


def count_file_types(repo_path: str) -> Dict[str, int]:
    """Zählt die Dateitypen im Repository.
    
    Args:
        repo_path: Pfad zum Repository.
        
    Returns:
        Dict[str, int]: Dictionary mit Dateitypen und deren Anzahlen.
    """
    file_counts = {}
    
    for root, _, files in os.walk(repo_path):
        for file in files:
            file_path = os.path.join(root, file)
            file_ext = os.path.splitext(file)[1].lower()
            file_name = os.path.basename(file_path)
            
            # Dateiendung prüfen
            if file_ext in CODE_FILE_EXTENSIONS:
                language = CODE_FILE_EXTENSIONS[file_ext]
                file_counts[language] = file_counts.get(language, 0) + 1
            
            # Spezielle Dateinamen prüfen
            if file_name in CODE_FILE_EXTENSIONS:
                language = CODE_FILE_EXTENSIONS[file_name]
                file_counts[language] = file_counts.get(language, 0) + 1
    
    return file_counts


def determine_repo_type(file_counts: Dict[str, int]) -> str:
    """Bestimmt den Repository-Typ basierend auf den Dateitypen.
    
    Args:
        file_counts: Dictionary mit Dateitypen und deren Anzahlen.
        
    Returns:
        str: Der erkannte Repository-Typ.
    """
    # Standardmäßig als Code-Repository betrachten
    repo_type = "code"
    
    # Prüfe, ob es sich um ein docs-only Repository handelt
    if (
        sum(file_counts.get(lang, 0) for lang in ["markdown", "rst", "latex", "pdf"]) > 0
        and sum(file_counts.get(lang, 0) for lang in ["python", "javascript", "java", "go", "rust", "ruby", "php", "cs", "cpp", "c", "sh", "ps1", "r"]) == 0
    ):
        repo_type = "docs-only"
    
    # Prüfe, ob es sich um ein Forschungs-Repository handelt
    elif (
        sum(file_counts.get(lang, 0) for lang in ["jupyter", "r", "python", "csv", "tsv", "xlsx", "xls", "ods", "json", "yaml"]) > 0
        and sum(file_counts.get(lang, 0) for lang in ["javascript", "java", "go", "rust", "ruby", "php", "cs", "cpp", "c", "sh", "ps1"]) == 0
    ):
        repo_type = "research"
    
    # Prüfe, ob es sich um ein Daten-Repository handelt
    elif (
        sum(file_counts.get(lang, 0) for lang in ["csv", "tsv", "xlsx", "xls", "ods", "json", "yaml", "sql", "db", "sqlite", "mdb", "accdb", "pkl", "pickle"]) > 0
        and sum(file_counts.get(lang, 0) for lang in ["python", "javascript", "java", "go", "rust", "ruby", "php", "cs", "cpp", "c", "sh", "ps1", "r"]) == 0
    ):
        repo_type = "data"
    
    # Prüfe, ob es sich um ein Template-Repository handelt
    elif (
        sum(file_counts.get(lang, 0) for lang in ["json", "yaml", "toml", "ini", "cfg", "conf", "xml", "xsl", "xslt", "svg", "html", "css", "scss", "sass", "less", "styl"]) > 0
        and sum(file_counts.get(lang, 0) for lang in ["python", "javascript", "java", "go", "rust", "ruby", "php", "cs", "cpp", "c", "sh", "ps1", "r"]) == 0
    ):
        repo_type = "templates"
    
    # Prüfe, ob es sich um ein Konfigurations-Repository handelt
    elif (
        sum(file_counts.get(lang, 0) for lang in ["yaml", "yml", "json", "toml", "ini", "cfg", "conf", "tf", "tfvars", "hcl", "env", "properties", "xml", "xsl", "xslt", "svg", "html", "css", "scss", "sass", "less", "styl", "sh", "ps1"]) > 0
        and sum(file_counts.get(lang, 0) for lang in ["python", "javascript", "java", "go", "rust", "ruby", "php", "cs", "cpp", "c", "r"]) == 0
    ):
        repo_type = "configuration"
    
    # Prüfe, ob es sich um ein Projektmanagement-Repository handelt
    elif (
        sum(file_counts.get(lang, 0) for lang in ["md", "txt", "json", "yaml", "csv", "tsv", "xlsx", "xls", "ods", "docx", "doc", "odt", "pptx", "ppt", "odp", "pdf", "jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp", "mp3", "wav", "ogg", "flac", "mp4", "avi", "mkv", "mov", "wmv", "flv", "webm", "zip", "tar", "gz", "7z", "rar", "xz", "bz2"]) > 0
        and sum(file_counts.get(lang, 0) for lang in ["python", "javascript", "java", "go", "rust", "ruby", "php", "cs", "cpp", "c", "sh", "ps1", "r"]) == 0
    ):
        repo_type = "project-management"
    
    return repo_type


def determine_dominant_language(file_counts: Dict[str, int]) -> Optional[str]:
    """Bestimmt die dominante Programmiersprache im Repository.
    
    Args:
        file_counts: Dictionary mit Dateitypen und deren Anzahlen.
        
    Returns:
        Optional[str]: Die dominante Programmiersprache oder None.
    """
    if not file_counts:
        return None
    
    # Filtere nur Programmiersprachen
    language_counts = {lang: count for lang, count in file_counts.items() if lang in LANGUAGE_VALIDATION_COMMANDS}
    
    if not language_counts:
        return None
    
    # Sortiere nach Anzahl der Dateien
    sorted_languages = sorted(language_counts.items(), key=lambda item: item[1], reverse=True)
    
    return sorted_languages[0][0] if sorted_languages else None


def get_validation_commands(repo_type: str, dominant_language: Optional[str]) -> Dict[str, str]:
    """Gibt die passenden Validierungskommandos für den Repository-Typ und die dominante Sprache zurück.
    
    Args:
        repo_type: Der erkannte Repository-Typ.
        dominant_language: Die dominante Programmiersprache.
        
    Returns:
        Dict[str, str]: Dictionary mit Validierungskommandos.
    """
    commands = {}
    
    # Standard-Validierungskommandos für den Repository-Typ
    if repo_type in DEFAULT_VALIDATION_COMMANDS:
        type_commands = DEFAULT_VALIDATION_COMMANDS[repo_type].get("commands", {})
        if isinstance(type_commands, dict):
            commands.update(type_commands)
    
    # Sprachspezifische Validierungskommandos
    if dominant_language and dominant_language in LANGUAGE_VALIDATION_COMMANDS:
        language_commands = LANGUAGE_VALIDATION_COMMANDS[dominant_language]
        commands.update(language_commands)
    
    return commands
