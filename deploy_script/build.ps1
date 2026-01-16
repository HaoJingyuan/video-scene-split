docker login --username=hjy@26847949 dcc-cloud2-cn-beijing.cr.volces.com -p "Aa987456"
docker build -t dcc-cloud2-cn-beijing.cr.volces.com/dcc-cloud/transnetv2:0.0.1 -f ../Dockerfile ../
docker push dcc-cloud2-cn-beijing.cr.volces.com/dcc-cloud/transnetv2:0.0.1
s deploy