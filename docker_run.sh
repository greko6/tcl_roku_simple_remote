docker kill myroku
docker rm myroku
#exit

docker run -it \
  --restart "always" \
  --name "myroku" \
  -p 5050:5000 \
  -d greko6/roku
