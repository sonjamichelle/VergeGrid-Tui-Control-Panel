from setuptools import setup, find_packages

setup(
    name="vergegrid-tui",
    version="0.1.0",
    packages=find_packages("src"),
    package_dir={"": "src"},
    install_requires=[
        "psutil",
        "rich"
    ],
    entry_points={
        "console_scripts": [
            "vgcc-tui=src.tui.core:main"
        ]
    }
)
