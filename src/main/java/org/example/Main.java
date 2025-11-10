package org.example;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.cdimascio.dotenv.Dotenv;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.Locale;


public class Main {
    private static final double LAT = 55.75;
    private static final double LON = 37.62;
    private static final int LIMIT = 5;

    public static void main(String[] args) {
        Dotenv dotenv = Dotenv.configure()
                .ignoreIfMissing()
                .load();

        String apiKey = dotenv.get("YANDEX_WEATHER_API_KEY");

        if (apiKey == null || apiKey.isEmpty()) {
            apiKey = System.getenv("YANDEX_WEATHER_API_KEY");
        }

        if (apiKey == null || apiKey.isEmpty()) {
            System.err.println("Не найден API-ключ YANDEX_WEATHER_API_KEY ни в .env, ни в переменных окружения");
            System.err.println("Добавьте его в .env или задайте переменную окружения YANDEX_WEATHER_API_KEY");
            return;
        }

        try {
            // ВАЖНО: Locale.US, чтобы были точки в lat/lon
            String url = String.format(
                    Locale.US,
                    "https://api.weather.yandex.ru/v2/forecast?lat=%f&lon=%f&limit=%d",
                    LAT, LON, LIMIT
            );

            HttpClient client = HttpClient.newHttpClient();

            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .header("X-Yandex-Weather-Key", apiKey)
                    .GET()
                    .build();

            HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());

            System.out.println("=== Полный JSON ответ ===");
            System.out.println(response.body());

            ObjectMapper mapper = new ObjectMapper();
            JsonNode root = mapper.readTree(response.body());

            JsonNode factNode = root.path("fact");
            JsonNode tempNode = factNode.path("temp");

            if (!tempNode.isMissingNode() && tempNode.isNumber()) {
                int currentTemp = tempNode.asInt();
                System.out.println("\nТекущая температура: " + currentTemp + "°C");
            } else {
                System.out.println("\nНе удалось корректно прочитать fact.temp");
            }

            JsonNode forecasts = root.path("forecasts");
            if (!forecasts.isArray() || forecasts.size() == 0) {
                System.out.println("Нет данных в forecasts для расчёта средней температуры.");
                return;
            }

            double sum = 0;
            int count = 0;

            int daysToUse = Math.min(LIMIT, forecasts.size());
            for (int i = 0; i < daysToUse; i++) {
                JsonNode tempAvgNode = forecasts.get(i)
                        .path("parts")
                        .path("day")
                        .path("temp_avg");

                if (!tempAvgNode.isMissingNode() && tempAvgNode.isNumber()) {
                    sum += tempAvgNode.asDouble();
                    count++;
                }
            }

            System.out.println("\n=== Средняя температура по прогнозу ===");
            System.out.println("Запрошено суток (limit): " + LIMIT);
            System.out.println("Учтено суток (есть temp_avg): " + count);

            if (count > 0) {
                double avg = sum / count;
                System.out.println("Средняя температура: " + avg + "°C");
            } else {
                System.out.println("Не удалось найти ни одного значения parts.day.temp_avg.");
            }

        } catch (IOException | InterruptedException e) {
            e.printStackTrace();
        }
    }
}
