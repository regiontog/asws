# Running autobahn tests 
```bash
git clone https://github.com/regiontog/asws
cd asws/tests
python3.6 fuzzingserver.py &

python2.7 -mvirtualenv wstest
. wstest/bin/activate (linux)
./wstest/Scripts/activate.bat (windows)

pip install autobahn
wstest -m fuzzingclient
open reports/servers/index.html
```