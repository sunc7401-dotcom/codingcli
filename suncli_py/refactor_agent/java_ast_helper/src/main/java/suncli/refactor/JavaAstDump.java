package suncli.refactor;

import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import com.github.javaparser.ast.body.EnumDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.RecordDeclaration;
import com.github.javaparser.ast.expr.FieldAccessExpr;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.expr.NameExpr;
import com.github.javaparser.ast.nodeTypes.NodeWithSimpleName;
import com.github.javaparser.resolution.declarations.ResolvedFieldDeclaration;
import com.github.javaparser.resolution.declarations.ResolvedMethodDeclaration;
import com.github.javaparser.resolution.declarations.ResolvedValueDeclaration;
import com.github.javaparser.symbolsolver.JavaSymbolSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.CombinedTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.JavaParserTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.ReflectionTypeSolver;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Stream;

public final class JavaAstDump {
    private JavaAstDump() {
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            throw new IllegalArgumentException("Usage: JavaAstDump <root> <relative-java-file>...");
        }
        Path root = Path.of(args[0]).toAbsolutePath().normalize();
        configureSymbolSolver(root);
        StringBuilder out = new StringBuilder();
        out.append("{\"files\":[");
        for (int index = 1; index < args.length; index++) {
            if (index > 1) {
                out.append(',');
            }
            String relativePath = args[index].replace('\\', '/');
            Path source = root.resolve(relativePath).normalize();
            CompilationUnit unit = StaticJavaParser.parse(source);
            writeFile(out, relativePath, unit);
        }
        out.append("]}");
        System.out.println(out);
    }

    private static void writeFile(StringBuilder out, String relativePath, CompilationUnit unit) {
        out.append('{');
        field(out, "path", relativePath);
        out.append(",\"classes\":[");
        List<Node> classes = new ArrayList<>();
        classes.addAll(unit.findAll(ClassOrInterfaceDeclaration.class));
        classes.addAll(unit.findAll(EnumDeclaration.class));
        classes.addAll(unit.findAll(RecordDeclaration.class));
        classes.sort(Comparator.comparingInt(JavaAstDump::startLine));
        for (int index = 0; index < classes.size(); index++) {
            if (index > 0) {
                out.append(',');
            }
            writeClass(out, classes.get(index));
        }
        out.append("],\"methods\":[");
        List<Node> methods = new ArrayList<>();
        methods.addAll(unit.findAll(MethodDeclaration.class));
        methods.addAll(unit.findAll(ConstructorDeclaration.class));
        methods.sort(Comparator.comparingInt(JavaAstDump::startLine));
        for (int index = 0; index < methods.size(); index++) {
            if (index > 0) {
                out.append(',');
            }
            writeMethod(out, methods.get(index));
        }
        out.append("],\"method_calls\":[");
        List<MethodCallExpr> methodCalls = unit.findAll(MethodCallExpr.class);
        methodCalls.sort(Comparator.comparingInt(JavaAstDump::startLine));
        for (int index = 0; index < methodCalls.size(); index++) {
            if (index > 0) {
                out.append(',');
            }
            writeMethodCall(out, methodCalls.get(index));
        }
        out.append("],\"field_accesses\":[");
        List<Node> fieldAccesses = collectFieldAccesses(unit);
        fieldAccesses.sort(Comparator.comparingInt(JavaAstDump::startLine));
        for (int index = 0; index < fieldAccesses.size(); index++) {
            if (index > 0) {
                out.append(',');
            }
            writeFieldAccess(out, fieldAccesses.get(index));
        }
        out.append("]}");
    }

    private static void writeClass(StringBuilder out, Node node) {
        out.append('{');
        field(out, "name", ((NodeWithSimpleName<?>) node).getNameAsString());
        out.append(',');
        number(out, "start_line", startLine(node));
        out.append(',');
        number(out, "end_line", endLine(node));
        out.append(',');
        field(out, "kind", classKind(node));
        out.append('}');
    }

    private static void writeMethod(StringBuilder out, Node node) {
        out.append('{');
        field(out, "name", ((NodeWithSimpleName<?>) node).getNameAsString());
        out.append(',');
        number(out, "start_line", startLine(node));
        out.append(',');
        number(out, "end_line", endLine(node));
        out.append(',');
        field(out, "signature", signature(node));
        out.append(',');
        field(out, "declaring_type", declaringType(node));
        out.append(',');
        field(out, "resolved_signature", resolvedSignature(node));
        out.append(',');
        bool(out, "symbol_resolved", !resolvedSignature(node).isEmpty());
        out.append(',');
        bool(out, "is_private", isPrivate(node));
        out.append(',');
        bool(out, "is_static", isStatic(node));
        out.append('}');
    }

    private static void writeMethodCall(StringBuilder out, MethodCallExpr call) {
        MethodResolution resolution = resolveMethod(call);
        out.append('{');
        field(out, "name", call.getNameAsString());
        out.append(',');
        number(out, "start_line", startLine(call));
        out.append(',');
        number(out, "end_line", endLine(call));
        out.append(',');
        field(out, "scope", call.getScope().map(Object::toString).orElse(""));
        out.append(',');
        field(out, "declaring_type", resolution.declaringType);
        out.append(',');
        field(out, "resolved_signature", resolution.signature);
        out.append(',');
        field(out, "return_type", resolution.returnType);
        out.append(',');
        bool(out, "symbol_resolved", resolution.resolved);
        out.append(',');
        field(out, "error", resolution.error);
        out.append('}');
    }

    private static void writeFieldAccess(StringBuilder out, Node node) {
        FieldResolution resolution = resolveField(node);
        out.append('{');
        field(out, "name", fieldName(node));
        out.append(',');
        number(out, "start_line", startLine(node));
        out.append(',');
        number(out, "end_line", endLine(node));
        out.append(',');
        field(out, "scope", fieldScope(node));
        out.append(',');
        field(out, "declaring_type", resolution.declaringType);
        out.append(',');
        field(out, "type", resolution.type);
        out.append(',');
        bool(out, "symbol_resolved", resolution.resolved);
        out.append(',');
        field(out, "error", resolution.error);
        out.append('}');
    }

    private static String classKind(Node node) {
        if (node instanceof ClassOrInterfaceDeclaration declaration) {
            return declaration.isInterface() ? "interface" : "class";
        }
        if (node instanceof EnumDeclaration) {
            return "enum";
        }
        if (node instanceof RecordDeclaration) {
            return "record";
        }
        return "class";
    }

    private static String signature(Node node) {
        if (node instanceof MethodDeclaration declaration) {
            return declaration.getDeclarationAsString(false, false, false);
        }
        if (node instanceof ConstructorDeclaration declaration) {
            return declaration.getDeclarationAsString(false, false, false);
        }
        return node.toString();
    }

    private static String declaringType(Node node) {
        if (node instanceof MethodDeclaration declaration) {
            try {
                return declaration.resolve().declaringType().getQualifiedName();
            } catch (Throwable ignored) {
                return lexicalOwnerName(node);
            }
        }
        if (node instanceof ConstructorDeclaration declaration) {
            try {
                return declaration.resolve().declaringType().getQualifiedName();
            } catch (Throwable ignored) {
                return lexicalOwnerName(node);
            }
        }
        return lexicalOwnerName(node);
    }

    private static String resolvedSignature(Node node) {
        try {
            if (node instanceof MethodDeclaration declaration) {
                return declaration.resolve().getQualifiedSignature();
            }
            if (node instanceof ConstructorDeclaration declaration) {
                return declaration.resolve().getQualifiedSignature();
            }
        } catch (Throwable ignored) {
            return "";
        }
        return "";
    }

    private static String lexicalOwnerName(Node node) {
        String typeName = node.findAncestor(ClassOrInterfaceDeclaration.class)
                .map(ClassOrInterfaceDeclaration::getNameAsString)
                .or(() -> node.findAncestor(EnumDeclaration.class).map(EnumDeclaration::getNameAsString))
                .or(() -> node.findAncestor(RecordDeclaration.class).map(RecordDeclaration::getNameAsString))
                .orElse("");
        if (typeName.isEmpty()) {
            return "";
        }
        return node.findCompilationUnit()
                .flatMap(unit -> unit.getPackageDeclaration().map(packageDeclaration -> packageDeclaration.getNameAsString()))
                .map(packageName -> packageName + "." + typeName)
                .orElse(typeName);
    }

    private static boolean isPrivate(Node node) {
        if (node instanceof MethodDeclaration declaration) {
            return declaration.isPrivate();
        }
        if (node instanceof ConstructorDeclaration declaration) {
            return declaration.isPrivate();
        }
        return false;
    }

    private static boolean isStatic(Node node) {
        if (node instanceof MethodDeclaration declaration) {
            return declaration.isStatic();
        }
        return false;
    }

    private static void configureSymbolSolver(Path root) throws IOException {
        CombinedTypeSolver typeSolver = new CombinedTypeSolver();
        typeSolver.add(new ReflectionTypeSolver(false));
        Set<Path> sourceRoots = new HashSet<>();
        try (Stream<Path> paths = Files.walk(root, 6)) {
            paths.filter(Files::isDirectory)
                    .filter(JavaAstDump::isJavaSourceRoot)
                    .map(Path::toAbsolutePath)
                    .map(Path::normalize)
                    .forEach(sourceRoots::add);
        }
        for (Path sourceRoot : sourceRoots) {
            typeSolver.add(new JavaParserTypeSolver(sourceRoot));
        }
        StaticJavaParser.getParserConfiguration()
                .setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_17)
                .setSymbolResolver(new JavaSymbolSolver(typeSolver));
    }

    private static boolean isJavaSourceRoot(Path path) {
        String normalized = path.toString().replace('\\', '/');
        return normalized.endsWith("src/main/java") || normalized.endsWith("src/test/java");
    }

    private static List<Node> collectFieldAccesses(CompilationUnit unit) {
        List<Node> accesses = new ArrayList<>();
        accesses.addAll(unit.findAll(FieldAccessExpr.class));
        for (NameExpr name : unit.findAll(NameExpr.class)) {
            FieldResolution resolution = resolveField(name);
            if (resolution.resolved) {
                accesses.add(name);
            }
        }
        return accesses;
    }

    private static MethodResolution resolveMethod(MethodCallExpr call) {
        try {
            ResolvedMethodDeclaration resolved = call.resolve();
            return new MethodResolution(
                    true,
                    resolved.declaringType().getQualifiedName(),
                    resolved.getQualifiedSignature(),
                    resolved.getReturnType().describe(),
                    "");
        } catch (Throwable error) {
            return new MethodResolution(false, "", "", "", trimError(error));
        }
    }

    private static FieldResolution resolveField(Node node) {
        try {
            ResolvedValueDeclaration valueDeclaration;
            if (node instanceof FieldAccessExpr fieldAccess) {
                valueDeclaration = fieldAccess.resolve();
            } else if (node instanceof NameExpr name) {
                valueDeclaration = name.resolve();
            } else {
                return new FieldResolution(false, "", "", "");
            }
            if (!valueDeclaration.isField()) {
                return new FieldResolution(false, "", "", "");
            }
            ResolvedFieldDeclaration field = valueDeclaration.asField();
            return new FieldResolution(
                    true,
                    field.declaringType().getQualifiedName(),
                    field.getType().describe(),
                    "");
        } catch (Throwable error) {
            return new FieldResolution(false, "", "", trimError(error));
        }
    }

    private static String fieldName(Node node) {
        if (node instanceof FieldAccessExpr fieldAccess) {
            return fieldAccess.getNameAsString();
        }
        if (node instanceof NameExpr name) {
            return name.getNameAsString();
        }
        return "";
    }

    private static String fieldScope(Node node) {
        if (node instanceof FieldAccessExpr fieldAccess) {
            return fieldAccess.getScope().toString();
        }
        return "";
    }

    private static String trimError(Throwable error) {
        String message = error.getClass().getSimpleName() + ": " + String.valueOf(error.getMessage());
        return message.length() > 240 ? message.substring(0, 240) : message;
    }

    private static int startLine(Node node) {
        return node.getRange().map(range -> range.begin.line).orElse(1);
    }

    private static int endLine(Node node) {
        return node.getRange().map(range -> range.end.line).orElse(startLine(node));
    }

    private static void field(StringBuilder out, String name, String value) {
        out.append('"').append(escape(name)).append("\":\"").append(escape(value)).append('"');
    }

    private static void number(StringBuilder out, String name, int value) {
        out.append('"').append(escape(name)).append("\":").append(value);
    }

    private static void bool(StringBuilder out, String name, boolean value) {
        out.append('"').append(escape(name)).append("\":").append(value);
    }

    private static String escape(String value) {
        StringBuilder escaped = new StringBuilder();
        for (int index = 0; index < value.length(); index++) {
            char current = value.charAt(index);
            switch (current) {
                case '\\' -> escaped.append("\\\\");
                case '"' -> escaped.append("\\\"");
                case '\n' -> escaped.append("\\n");
                case '\r' -> escaped.append("\\r");
                case '\t' -> escaped.append("\\t");
                default -> escaped.append(current);
            }
        }
        return escaped.toString();
    }

    private record MethodResolution(
            boolean resolved,
            String declaringType,
            String signature,
            String returnType,
            String error) {
    }

    private record FieldResolution(boolean resolved, String declaringType, String type, String error) {
    }
}
