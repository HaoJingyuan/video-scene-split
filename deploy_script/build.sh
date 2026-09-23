docker login --username=hjy@26847949 dcc-cloud2-cn-beijing.cr.volces.com -p "Aa987456"
docker build --platform linux/amd64 -t dcc-cloud2-cn-beijing.cr.volces.com/dcc-cloud/transnetv2:0.0.3 -f ../Dockerfile ../
docker push dcc-cloud2-cn-beijing.cr.volces.com/dcc-cloud/transnetv2:0.0.3
s deploy