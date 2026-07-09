package suncli.refactor;

import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import com.github.javaparser.ast.body.EnumDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.RecordDeclaration;
import com.github.javaparser.ast.nodeTypes.NodeWithSimpleName;
import com.github.javaparser.ast.nodeTypes.NodeWithTokenRange;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

public final class JavaAstDump {
    private JavaAstDump() {
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            throw new IllegalArgumentException("Usage: JavaAstDump <root> <relative-java-file>...");
        }
        Path root = Path.of(args[0]).toAbsolutePath().normalize();
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
        bool(out, "is_private", isPrivate(node));
        out.append(',');
        bool(out, "is_static", isStatic(node));
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
}
