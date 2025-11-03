Prérequis:

Python 3.12
MongoDB
Package Python: fastapi, uvicorn

1) Lancer mongodb.
2) S'assurer que la base de données crunchbase et la collection artists existe.
3) Lancer l'application FastAPI dans un terminal à l'emplacement du fichier main.py.
5) Vous pouvez consulter et tester les endpoints.

La configuration de la connexion à mongodb est modifiable via le fichier .env.

Endpoints disponibles:

- GET /artists -> pour lister tous les artistes
- GET /artists/search -> pour rechercher un artiste par son nom, prénom et id
- PUT /artists/{artist_id} -> pour mettre à jour un artiste
- DELETE /artists/{artist_id}  -> pour supprimer un artiste

Tous les endpoints sont disponibles via l'url: http://localhost:8000/docs.
  


