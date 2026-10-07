# iNaturalist harvestor
Cronjob to harvest iNaturalist data from specific project

```shell
docker build . -t harvest
docker run --env-file .env harvest
```