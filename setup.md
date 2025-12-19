## setup

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

python script.py "C:\path\to\your\folder"

Hide pass, pass, pass, pass rows in Sheets afterwards:

in f1:

=COUNTIF(B2:E2, "<>Pass")>0

Then hide "false" rows
