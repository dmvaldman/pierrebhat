const fs = require('fs');
const esprima = require('esprima');  // Install via `npm install esprima`

function parseJavaScript(filePath) {
    const code = fs.readFileSync(filePath, 'utf-8');
    const ast = esprima.parseScript(code);

    const result = {
        classes: [],
        functions: [],
        dependencies: []
    };

    // Traverse AST and populate the result object
    // This is a simplified traversal. You'd expand on this based on your needs.
    ast.body.forEach(node => {
        // Functions
        if (node.type === 'FunctionDeclaration') {
            result.functions.push(node.id.name);
        }

        // Classes
        if (node.type === 'ClassDeclaration') {
            result.classes.push(node.id.name);
        }

        // Import Statements for dependencies
        if (node.type === 'ImportDeclaration') {
            // Assuming you want the whole import path (e.g., "./module/file")
            result.dependencies.push(node.source.value);

            // If you want individual imported members, you can further process node.specifiers
            node.specifiers.forEach(specifier => {
                result.dependencies.push(specifier.local.name);
            });
        }

        // CommonJS require() for dependencies
        if (node.type === 'CallExpression' && node.callee.name === 'require') {
            result.dependencies.push(node.arguments[0].value);
        }

        // You can continue to expand this for other constructs as needed
    });

    return result;
}

const filePath = process.argv[2];
const output = parseJavaScript(filePath);
console.log(JSON.stringify(output));