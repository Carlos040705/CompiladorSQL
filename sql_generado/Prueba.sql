CREATE TABLE IF NOT EXISTS estudiante (
    nombre VARCHAR(255) UNIQUE,
    matricula SERIAL,
    edad INTEGER,
    peso NUMERIC(10, 5)
);

INSERT INTO estudiante (nombre, edad, peso) VALUES ('Jose Cruz Castillo', 67, 160.0);

INSERT INTO estudiante (nombre, edad, peso) VALUES ('Bernardo Manuel Vargas', 23, 85);

UPDATE estudiante SET nombre = 'José Ángel Figueroa' WHERE edad > 60;
