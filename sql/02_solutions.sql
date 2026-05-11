-- Part 1, Task 1
SET search_path TO part1;
SELECT v.maker, v.model
FROM Vehicle v
JOIN Motorcycle m ON m.model = v.model
WHERE m.horsepower > 150
  AND m.price < 20000
  AND m.type = 'Sport'
ORDER BY m.horsepower DESC;

-- Part 1, Task 2
SET search_path TO part1;
SELECT maker, model, horsepower, engine_capacity, vehicle_type
FROM (
    SELECT v.maker, v.model, c.horsepower, c.engine_capacity, 'Car' AS vehicle_type
    FROM Vehicle v
    JOIN Car c ON c.model = v.model
    WHERE c.horsepower > 150 AND c.engine_capacity < 3 AND c.price < 35000

    UNION ALL

    SELECT v.maker, v.model, m.horsepower, m.engine_capacity, 'Motorcycle' AS vehicle_type
    FROM Vehicle v
    JOIN Motorcycle m ON m.model = v.model
    WHERE m.horsepower > 150 AND m.engine_capacity < 1.5 AND m.price < 20000

    UNION ALL

    SELECT v.maker, v.model, NULL::INT AS horsepower, NULL::DECIMAL(4, 2) AS engine_capacity, 'Bicycle' AS vehicle_type
    FROM Vehicle v
    JOIN Bicycle b ON b.model = v.model
    WHERE b.gear_count > 18 AND b.price < 4000
) s
ORDER BY horsepower DESC NULLS LAST;

-- Part 2, Task 1
SET search_path TO part2;
WITH car_stats AS (
    SELECT c.name AS car_name, c.class AS car_class,
           AVG(r.position)::DECIMAL(10, 4) AS average_position,
           COUNT(*) AS race_count
    FROM Cars c
    JOIN Results r ON r.car = c.name
    GROUP BY c.name, c.class
),
ranked AS (
    SELECT *, RANK() OVER (PARTITION BY car_class ORDER BY average_position) AS place_in_class
    FROM car_stats
)
SELECT car_name, car_class, average_position, race_count
FROM ranked
WHERE place_in_class = 1
ORDER BY average_position,
         CASE car_class
             WHEN 'Convertible' THEN 1
             WHEN 'SportsCar' THEN 2
             WHEN 'SUV' THEN 3
             WHEN 'Luxury Sedan' THEN 4
             WHEN 'Sedan' THEN 5
             WHEN 'Coupe' THEN 6
             WHEN 'Hatchback' THEN 7
             WHEN 'Pickup' THEN 8
             ELSE 9
         END;

-- Part 2, Task 2
SET search_path TO part2;
SELECT c.name AS car_name, c.class AS car_class,
       AVG(r.position)::DECIMAL(10, 4) AS average_position,
       COUNT(*) AS race_count,
       cl.country AS car_country
FROM Cars c
JOIN Classes cl ON cl.class = c.class
JOIN Results r ON r.car = c.name
GROUP BY c.name, c.class, cl.country
ORDER BY average_position, c.name
LIMIT 1;

-- Part 2, Task 3
SET search_path TO part2;
WITH class_stats AS (
    SELECT c.class AS car_class,
           AVG(r.position)::DECIMAL(10, 4) AS class_average_position,
           COUNT(*) AS total_races
    FROM Cars c
    JOIN Results r ON r.car = c.name
    GROUP BY c.class
),
best_classes AS (
    SELECT *
    FROM class_stats
    WHERE class_average_position = (SELECT MIN(class_average_position) FROM class_stats)
),
car_stats AS (
    SELECT c.name AS car_name, c.class AS car_class,
           AVG(r.position)::DECIMAL(10, 4) AS average_position,
           COUNT(*) AS race_count
    FROM Cars c
    JOIN Results r ON r.car = c.name
    GROUP BY c.name, c.class
)
SELECT cs.car_name, cs.car_class, cs.average_position, cs.race_count,
       cl.country AS car_country, bc.total_races
FROM car_stats cs
JOIN best_classes bc ON bc.car_class = cs.car_class
JOIN Classes cl ON cl.class = cs.car_class
ORDER BY cs.car_name;

-- Part 2, Task 4
SET search_path TO part2;
WITH car_stats AS (
    SELECT c.name AS car_name, c.class AS car_class,
           AVG(r.position)::DECIMAL(10, 4) AS average_position,
           COUNT(*) AS race_count
    FROM Cars c
    JOIN Results r ON r.car = c.name
    GROUP BY c.name, c.class
),
class_stats AS (
    SELECT car_class,
           AVG(average_position) AS class_average_position,
           COUNT(*) AS cars_in_class
    FROM car_stats
    GROUP BY car_class
)
SELECT cs.car_name, cs.car_class, cs.average_position, cs.race_count,
       cl.country AS car_country
FROM car_stats cs
JOIN class_stats cls ON cls.car_class = cs.car_class
JOIN Classes cl ON cl.class = cs.car_class
WHERE cls.cars_in_class >= 2
  AND cs.average_position < cls.class_average_position
ORDER BY cs.car_class, cs.average_position;

-- Part 2, Task 5
SET search_path TO part2;
WITH car_stats AS (
    SELECT c.name AS car_name, c.class AS car_class,
           AVG(r.position)::DECIMAL(10, 4) AS average_position,
           COUNT(*) AS race_count
    FROM Cars c
    JOIN Results r ON r.car = c.name
    GROUP BY c.name, c.class
),
class_totals AS (
    SELECT c.class AS car_class, COUNT(r.*) AS total_races
    FROM Cars c
    JOIN Results r ON r.car = c.name
    GROUP BY c.class
),
low_classes AS (
    SELECT cs.car_class, COUNT(all_cars.*) AS low_position_count
    FROM car_stats cs
    JOIN car_stats all_cars ON all_cars.car_class = cs.car_class
    WHERE cs.average_position > 3.0
    GROUP BY cs.car_class
)
SELECT cs.car_name, cs.car_class, cs.average_position, cs.race_count,
       cl.country AS car_country, ct.total_races, lc.low_position_count
FROM car_stats cs
JOIN low_classes lc ON lc.car_class = cs.car_class
JOIN class_totals ct ON ct.car_class = cs.car_class
JOIN Classes cl ON cl.class = cs.car_class
WHERE cs.average_position > 3.0
ORDER BY lc.low_position_count DESC, cs.car_class, cs.car_name;

-- Part 3, Task 1
SET search_path TO part3;
SELECT c.name, c.email, c.phone,
       COUNT(*) AS total_bookings,
       STRING_AGG(DISTINCT h.name, ', ' ORDER BY h.name) AS hotels,
       AVG(b.check_out_date - b.check_in_date)::DECIMAL(10, 4) AS average_stay
FROM Customer c
JOIN Booking b ON b.ID_customer = c.ID_customer
JOIN Room r ON r.ID_room = b.ID_room
JOIN Hotel h ON h.ID_hotel = r.ID_hotel
GROUP BY c.ID_customer, c.name, c.email, c.phone
HAVING COUNT(*) > 2 AND COUNT(DISTINCT h.ID_hotel) > 1
ORDER BY total_bookings DESC, c.name;

-- Part 3, Task 2
SET search_path TO part3;
WITH active_customers AS (
    SELECT c.ID_customer, c.name,
           COUNT(*) AS total_bookings,
           COUNT(DISTINCT h.ID_hotel) AS unique_hotels,
           SUM(r.price)::DECIMAL(10, 2) AS total_spent
    FROM Customer c
    JOIN Booking b ON b.ID_customer = c.ID_customer
    JOIN Room r ON r.ID_room = b.ID_room
    JOIN Hotel h ON h.ID_hotel = r.ID_hotel
    GROUP BY c.ID_customer, c.name
    HAVING COUNT(*) > 2 AND COUNT(DISTINCT h.ID_hotel) > 1
),
rich_customers AS (
    SELECT c.ID_customer
    FROM Customer c
    JOIN Booking b ON b.ID_customer = c.ID_customer
    JOIN Room r ON r.ID_room = b.ID_room
    GROUP BY c.ID_customer
    HAVING SUM(r.price) > 500
)
SELECT ac.ID_customer, ac.name, ac.total_bookings, ac.total_spent, ac.unique_hotels
FROM active_customers ac
JOIN rich_customers rc ON rc.ID_customer = ac.ID_customer
ORDER BY ac.total_spent;

-- Part 3, Task 3
SET search_path TO part3;
WITH hotel_categories AS (
    SELECT h.ID_hotel, h.name,
           CASE
               WHEN AVG(r.price) < 175 THEN 'Дешевый'
               WHEN AVG(r.price) <= 300 THEN 'Средний'
               ELSE 'Дорогой'
           END AS hotel_type
    FROM Hotel h
    JOIN Room r ON r.ID_hotel = h.ID_hotel
    GROUP BY h.ID_hotel, h.name
),
customer_hotels AS (
    SELECT DISTINCT c.ID_customer, c.name, hc.name AS hotel_name, hc.hotel_type
    FROM Customer c
    JOIN Booking b ON b.ID_customer = c.ID_customer
    JOIN Room r ON r.ID_room = b.ID_room
    JOIN hotel_categories hc ON hc.ID_hotel = r.ID_hotel
),
preferences AS (
    SELECT ID_customer, name,
           CASE
               WHEN BOOL_OR(hotel_type = 'Дорогой') THEN 'Дорогой'
               WHEN BOOL_OR(hotel_type = 'Средний') THEN 'Средний'
               ELSE 'Дешевый'
           END AS preferred_hotel_type,
           STRING_AGG(hotel_name, ',' ORDER BY hotel_name) AS visited_hotels
    FROM customer_hotels
    GROUP BY ID_customer, name
)
SELECT ID_customer, name, preferred_hotel_type, visited_hotels
FROM preferences
ORDER BY CASE preferred_hotel_type
             WHEN 'Дешевый' THEN 1
             WHEN 'Средний' THEN 2
             ELSE 3
         END,
         ID_customer;

-- Part 4, Task 1
SET search_path TO part4;
WITH RECURSIVE subordinates AS (
    SELECT EmployeeID, Name, ManagerID, DepartmentID, RoleID
    FROM Employees
    WHERE EmployeeID = 1
    UNION ALL
    SELECT e.EmployeeID, e.Name, e.ManagerID, e.DepartmentID, e.RoleID
    FROM Employees e
    JOIN subordinates s ON e.ManagerID = s.EmployeeID
),
employee_info AS (
    SELECT s.EmployeeID, s.Name AS EmployeeName, s.ManagerID,
           d.DepartmentName, r.RoleName,
           STRING_AGG(DISTINCT p.ProjectName, ', ' ORDER BY p.ProjectName) AS ProjectNames,
           STRING_AGG(DISTINCT t.TaskName, ', ' ORDER BY t.TaskName) AS TaskNames
    FROM subordinates s
    JOIN Departments d ON d.DepartmentID = s.DepartmentID
    JOIN Roles r ON r.RoleID = s.RoleID
    LEFT JOIN Projects p ON p.DepartmentID = s.DepartmentID
    LEFT JOIN Tasks t ON t.AssignedTo = s.EmployeeID
    GROUP BY s.EmployeeID, s.Name, s.ManagerID, d.DepartmentName, r.RoleName
)
SELECT EmployeeID, EmployeeName, ManagerID, DepartmentName, RoleName, ProjectNames, TaskNames
FROM employee_info
ORDER BY EmployeeName;

-- Part 4, Task 2
SET search_path TO part4;
WITH RECURSIVE subordinates AS (
    SELECT EmployeeID, Name, ManagerID, DepartmentID, RoleID
    FROM Employees
    WHERE EmployeeID = 1
    UNION ALL
    SELECT e.EmployeeID, e.Name, e.ManagerID, e.DepartmentID, e.RoleID
    FROM Employees e
    JOIN subordinates s ON e.ManagerID = s.EmployeeID
),
employee_info AS (
    SELECT s.EmployeeID, s.Name AS EmployeeName, s.ManagerID,
           d.DepartmentName, r.RoleName,
           STRING_AGG(DISTINCT p.ProjectName, ', ' ORDER BY p.ProjectName) AS ProjectNames,
           STRING_AGG(DISTINCT t.TaskName, ', ' ORDER BY t.TaskName) AS TaskNames,
           COUNT(DISTINCT t.TaskID) AS TotalTasks,
           COUNT(DISTINCT child.EmployeeID) AS TotalSubordinates
    FROM subordinates s
    JOIN Departments d ON d.DepartmentID = s.DepartmentID
    JOIN Roles r ON r.RoleID = s.RoleID
    LEFT JOIN Projects p ON p.DepartmentID = s.DepartmentID
    LEFT JOIN Tasks t ON t.AssignedTo = s.EmployeeID
    LEFT JOIN Employees child ON child.ManagerID = s.EmployeeID
    GROUP BY s.EmployeeID, s.Name, s.ManagerID, d.DepartmentName, r.RoleName
)
SELECT EmployeeID, EmployeeName, ManagerID, DepartmentName, RoleName,
       ProjectNames, TaskNames, TotalTasks, TotalSubordinates
FROM employee_info
ORDER BY EmployeeName;

-- Part 4, Task 3
SET search_path TO part4;
WITH RECURSIVE manager_tree AS (
    SELECT e.EmployeeID AS manager_id, e.EmployeeID AS subordinate_id
    FROM Employees e
    UNION ALL
    SELECT mt.manager_id, e.EmployeeID
    FROM manager_tree mt
    JOIN Employees e ON e.ManagerID = mt.subordinate_id
),
manager_counts AS (
    SELECT manager_id, COUNT(*) - 1 AS TotalSubordinates
    FROM manager_tree
    GROUP BY manager_id
),
employee_info AS (
    SELECT e.EmployeeID, e.Name AS EmployeeName, e.ManagerID,
           d.DepartmentName, r.RoleName,
           STRING_AGG(DISTINCT p.ProjectName, ', ' ORDER BY p.ProjectName) AS ProjectNames,
           STRING_AGG(DISTINCT t.TaskName, ', ' ORDER BY t.TaskName) AS TaskNames,
           mc.TotalSubordinates
    FROM Employees e
    JOIN Roles r ON r.RoleID = e.RoleID
    JOIN Departments d ON d.DepartmentID = e.DepartmentID
    JOIN manager_counts mc ON mc.manager_id = e.EmployeeID
    LEFT JOIN Projects p ON p.DepartmentID = e.DepartmentID
    LEFT JOIN Tasks t ON t.AssignedTo = e.EmployeeID
    WHERE r.RoleName = 'Менеджер' AND mc.TotalSubordinates > 0
    GROUP BY e.EmployeeID, e.Name, e.ManagerID, d.DepartmentName, r.RoleName, mc.TotalSubordinates
)
SELECT EmployeeID, EmployeeName, ManagerID, DepartmentName, RoleName,
       ProjectNames, TaskNames, TotalSubordinates
FROM employee_info
ORDER BY EmployeeID;
