Esta carpeta contiene un sistema para armar diariamente un informe de reseñas que se distribuira a los restaurantes.

Las reseñas se obtienen de tres plataformas: Rappi, Pedidos Ya y Mercado Libre

La informacion de Rappi y Pedidos Ya se extrae de los portales utilizando APIs de consulta. La informacion de Mercado Libre se importa con dos archivos CSV uno con las reseñas y otro con el total de ordenes.

El sistema genera al final un pdf para cada grupo de restaurantes. 
El pdf contiene 2 indices en la parte superior (cantidadDeErrores/cantidadDeOrdenes y cantidadDeErroresGraves/cantidadDeErrores)

Luego se listan las reseñas obtenidas para los restaurantes. Aquellos pedidos que son errores muy graves se resaltan para llamar la atencion.

Tambien se suman al informe los reclamos hechos por los clientes