-- Django's test runner creates and drops a separate "test_careslot" database.
GRANT ALL PRIVILEGES ON `test_careslot`.* TO 'careslot'@'%';
FLUSH PRIVILEGES;
