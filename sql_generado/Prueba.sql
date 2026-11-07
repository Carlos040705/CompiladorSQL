CREATE TABLE IF NOT EXISTS estudiante (
    nombre VARCHAR(255) UNIQUE,
    matricula SERIAL,
    edad INTEGER,
    peso NUMERIC(10, 5)
);

SELECT * FROM estudiante WHERE nombre = 'Jose Cruz Castillo';

UPDATE estudiante SET nombre = 'Jose Cruz Castillo';

DELETE FROM estudiante WHERE nombre = 'Jose Cruz Castillo';

SELECT * FROM estudiante WHERE nombre = 'Jose Cruz Castillo';

INSERT INTO estudiante (nombre, edad, peso) VALUES ('Jose Cruz Castillo', 67, 160.0);

SELECT * FROM estudiante WHERE (edad + 2) % 5 = 0 AND peso > -10;

SELECT * FROM estudiante WHERE NOT (edad > 18 AND nombre = 'Jose');
