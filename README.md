[![Documentation Status](https://readthedocs.org/projects/adopt-net0/badge/?version=latest)](https://adopt-net0.readthedocs.io/en/latest/?badge=latest)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
![Testing](https://github.com/UU-ER/AdOpT-NET0/actions/workflows/testing.yml/badge.svg?branch=main)


To get started you need to follow the subsequent steps:
- Make sure you have Python installed on your computer (it needs to be version 3.12!)
- Clone the repository to you drive
- Create a virtual environment for this project. You can do this using PyCharm:
    - Open the project in PyCharm
    - Go to File -> Settings -> <project_name> -> Python Interpreter
    - Select Add Local Inerpreter from the Add Interpreter
    - In the left-hand pane of the Add Python Interpreter dialog, select Virtualenv Environment
    - Add a Base Interpreter (select Python 3.12)
- Install all required packages to your virtual environment by using pip. In PyCharm you can do this with:
    - Move to the terminal in PyCharm, it is located on the bottom. If the virtual environment was correctly installed, you should see a (venv) in front of the path
    - Execute the command pip install -r requirements.txt to install all requirements in your virtual environment
- Now, you can run main.py with python 3.12. In PyCharm, you can do this:
    - Click on Edit configuration, in the upper right corner of the screen
    - Click Add new...
    - Name your configuration as you like (e.g. Run main)
    - Select a Python 3.12 as an interpreter and click ok
    - You can run the model.

If you want to create a new documentation website, you can use the PyCharm Terminal:
    - Move to the docs folder by executing 'cd docs' in the terminal
    - Depending on the shell you use, either execute .\make html or make html
    - Find the documentation in docs\build\html\index.html and open it in your browser

To open the visualization website, type 'streamlit run src/visualization/streamlit_app.py' in the terminal.

https://peps.python.org/pep-0008/

Run one test only (with the coverage package):
coverage run -m pytest -k "test_slow_dynamics" src/test/test_technologies.py
Run all test in one test suit:
coverage run -m pytest -k src/test/test_networks.py