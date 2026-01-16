docker login --username=jingyuan.hao@44633857 rec-cn-beijing.cr.volces.com -p Hh987456
docker build -t rec-cn-beijing.cr.volces.com/animation/transnetv2-test:0.0.1 -f ../Dockerfile ../
docker push rec-cn-beijing.cr.volces.com/animation/transnetv2-test:0.0.1
s deploy