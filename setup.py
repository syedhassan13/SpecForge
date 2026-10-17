"""Setup script for SpecLoop."""

from setuptools import setup, find_packages

setup(
    name="specloop",
    version="0.1.0",
    description="Specification-Driven Verification Feedback Pipeline for LLM Coding Agents",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "openai>=1.30.0",
        "anthropic>=0.25.0",
        "icontract>=2.7.0",
        "typing_extensions>=4.5.0",
        "rich>=13.0.0",
        "click>=8.1.0",
        "tabulate>=0.9.0",
        "python-dotenv>=1.0.0",
    ],
    extras_require={
        "dev": ["pytest>=7.0", "crosshair-tool>=0.0.67"],
        "viz": ["matplotlib>=3.7.0", "pandas>=2.0.0"],
    },
    entry_points={
        "console_scripts": [
            "specloop=run_baseline:main",
        ],
    },
)
